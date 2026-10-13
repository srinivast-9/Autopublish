from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import chess
import chess.pgn
import numpy as np
import requests
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("CHESSBITS_DATA_DIR", "/tmp/chessbits-worker"))
JOBS_DIR = DATA / "jobs"
ASSETS = ROOT / "assets"
API_TOKEN = os.getenv("CHESSBITS_API_TOKEN", "")
MEDIA_SECRET = os.getenv("MEDIA_SIGNING_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
TTL = max(600, min(21600, int(os.getenv("MEDIA_TTL_SECONDS", "21600"))))
MAX_AUDIO = 100 * 1024 * 1024
MAX_TOTAL_AUDIO = 250 * 1024 * 1024
MAX_DURATION = 900
FPS = 12
ALLOWED_SUFFIXES = (".cloudfront.net", ".runwayml.com", ".runway.com", ".pixabay.com", ".pixabaycdn.com", ".ncs.io", ".googleapis.com")
TRANSIENT = (408, 425, 429, 500, 502, 503, 504)
LOG = logging.getLogger("chessbits")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI(title="Chess Bits Cloud Worker", version="0.1.0", docs_url=None, redoc_url=None)
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
PIECES: dict[str, Image.Image] = {}


class RenderRequest(BaseModel):
    pgn: str = Field(min_length=2, max_length=60000)
    voiceover_urls: list[str] = Field(min_length=1, max_length=8)
    video_type: str = Field(pattern="^(puzzle_short|longform)$")
    title: str = Field(default="Chess Bits", min_length=1, max_length=120)
    music_url: str | None = Field(default=None, max_length=4096)
    require_checkmate: bool = False


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {p.stderr.decode('utf-8', 'replace')[-1000:]}")
    return p


def load_pieces() -> None:
    global PIECES
    result = {}
    for color in ("w", "b"):
        for symbol in "KQRBNP":
            path = ASSETS / f"{color}{symbol.lower()}.png"
            if not path.is_file():
                raise RuntimeError(f"Missing Neo piece sprite {path.name}")
            result[color + symbol] = Image.open(path).convert("RGBA")
    if len(result) != 12:
        raise RuntimeError("Neo piece sprite set incomplete")
    PIECES = result


def validate_url(raw: str) -> str:
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError
        if not any(host.endswith(s) for s in ALLOWED_SUFFIXES):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Audio URL must be HTTPS on an approved Runway/CloudFront or music host.")
    return raw


def check_redirect(url: str) -> None:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower().rstrip(".")
        if u.scheme != "https" or not host or u.username or u.password or u.port not in (None, 443) or not any(host.endswith(s) for s in ALLOWED_SUFFIXES):
            raise ValueError
    except Exception:
        raise RuntimeError("Audio redirect targets an unapproved host; stopped safely.")


def download_audio(url: str, target: Path, current_total: int) -> int:
    current = validate_url(url)
    host = urlparse(current).hostname or "unknown"
    LOG.info("AUDIO_DOWNLOAD_START host=%s target=%s current_total=%d", host, target.name, current_total)
    last: Exception | None = None
    with requests.Session() as session:
        for attempt in range(3):
            tmp = target.with_suffix(target.suffix + ".part")
            try:
                tmp.unlink(missing_ok=True)
                for _ in range(6):
                    with session.get(current, stream=True, timeout=(10, 45), allow_redirects=False) as resp:
                        host = urlparse(current).hostname or "unknown"
                        LOG.info("AUDIO_HTTP_RESPONSE host=%s status=%d attempt=%d", host, resp.status_code, attempt + 1)
                        if resp.is_redirect or resp.is_permanent_redirect:
                            loc = resp.headers.get("Location")
                            if not loc:
                                raise RuntimeError("Provider redirect missing Location")
                            current = urljoin(current, loc)
                            check_redirect(current)
                            continue
                        if resp.status_code in TRANSIENT:
                            raise requests.HTTPError(f"transient status {resp.status_code}")
                        resp.raise_for_status()
                        ctype = (resp.headers.get("Content-Type") or "").split(";", 1)[0].lower().strip()
                        if ctype and not (ctype.startswith("audio/") or ctype in ("application/octet-stream", "binary/octet-stream")):
                            raise RuntimeError(f"Expected audio but got {ctype}")
                        if int(resp.headers.get("Content-Length") or 0) > MAX_AUDIO:
                            raise RuntimeError("Audio segment exceeds 100 MB")
                        size = 0
                        with tmp.open("wb") as out:
                            for chunk in resp.iter_content(256 * 1024):
                                if not chunk:
                                    continue
                                size += len(chunk)
                                if size > MAX_AUDIO or current_total + size > MAX_TOTAL_AUDIO:
                                    raise RuntimeError("Audio exceeds configured size limits")
                                out.write(chunk)
                        if size < 1024:
                            raise RuntimeError("Audio file too small")
                        tmp.replace(target)
                        LOG.info("AUDIO_DOWNLOAD_COMPLETE host=%s file=%s bytes=%d", host, target.name, size)
                        return size
                raise RuntimeError("Too many redirects")
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last = exc
                LOG.warning("AUDIO_DOWNLOAD_RETRY host=%s attempt=%d error=%s", urlparse(current).hostname or "unknown", attempt + 1, type(exc).__name__)
                if isinstance(exc, requests.HTTPError) and not any(str(code) in str(exc) for code in TRANSIENT):
                    break
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
            except Exception as exc:
                last = exc
                LOG.exception("AUDIO_DOWNLOAD_ABORT host=%s attempt=%d", urlparse(current).hostname or "unknown", attempt + 1)
                break
            finally:
                tmp.unlink(missing_ok=True)
    raise RuntimeError(f"Audio download failed ({type(last).__name__ if last else 'unknown'}); no partial file retained")


def probe_audio(path: Path) -> dict:
    LOG.info("AUDIO_PROBE_START file=%s size_bytes=%d", path.name, path.stat().st_size if path.exists() else -1)
    raw = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], 60)
    info = json.loads(raw.stdout)
    audios = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audios:
        raise RuntimeError("Audio contains no audio stream")
    duration = float(info.get("format", {}).get("duration") or audios[0].get("duration") or 0)
    if duration <= 0 or duration > MAX_DURATION:
        raise RuntimeError(f"Audio duration must be 0–{MAX_DURATION} seconds")
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], min(900, max(60, int(duration * 2))))
    LOG.info("AUDIO_PROBE_COMPLETE file=%s duration_seconds=%.2f codec=%s", path.name, duration, audios[0].get("codec_name", "unknown"))
    return {"duration": duration, "codec": audios[0].get("codec_name", "unknown")}


def make_narration(urls: list[str], work: Path) -> tuple[Path, dict]:
    parts = []
    downloaded = 0
    LOG.info("NARRATION_PREPARE segments=%d", len(urls))
    for idx, url in enumerate(urls):
        validate_url(url)
        LOG.info("NARRATION_SEGMENT_START index=%d", idx)
        path = work / f"narration_{idx}.audio"
        downloaded += download_audio(url, path, downloaded)
        probe_audio(path)
        parts.append(path)
        LOG.info("NARRATION_SEGMENT_READY index=%d", idx)
    output = work / "narration.mp3"
    if len(parts) == 1:
        run(["ffmpeg", "-y", "-i", str(parts[0]), "-vn", "-ac", "2", "-ar", "48000", "-b:a", "192k", str(output)], 900)
    else:
        concat = work / "concat.txt"
        concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-vn", "-ac", "2", "-ar", "48000", "-b:a", "192k", str(output)], 900)
    meta = probe_audio(output)
    for p in parts:
        p.unlink(missing_ok=True)
    return output, {**meta, "segments": len(parts), "bytes_downloaded": downloaded}


def parse_pgn(text: str, must_mate: bool) -> tuple[list[chess.Board], list[chess.Move], list[str], bool]:
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None or game.errors:
        raise RuntimeError("PGN is missing or has notation errors")
    board = game.board()
    states = [board.copy()]
    moves: list[chess.Move] = []
    sans: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise RuntimeError("PGN contains an illegal move")
        sans.append(board.san(move))
        moves.append(move)
        board.push(move)
        states.append(board.copy())
        if len(moves) > 250:
            raise RuntimeError("PGN exceeds the 250-half-move limit")
    if not moves:
        raise RuntimeError("PGN contains no moves")
    mate = board.is_checkmate()
    if must_mate and not mate:
        raise RuntimeError("Puzzle line does not end in checkmate; render blocked")
    return states, moves, sans, mate


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True):
    options = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
    for name in options:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


@lru_cache(maxsize=4)
def _background_base(size: tuple[int, int]) -> Image.Image:
    w, h = size
    top = np.array((14, 19, 22), dtype=np.float32)
    bot = np.array((8, 11, 15), dtype=np.float32)
    grad = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a = np.broadcast_to(top[None, None, :] * (1-grad) + bot[None, None, :] * grad, (h, w, 3)).astype(np.uint8).copy()
    base = Image.fromarray(a).convert("RGBA")
    glow = Image.new("RGBA", size, (0, 0, 0, 0)); d = ImageDraw.Draw(glow)
    d.ellipse((-w//5, h//10, w//2, 3*h//4), fill=(22, 87, 112, 40))
    d.ellipse((w//2, h//3, 6*w//5, h), fill=(176, 121, 35, 30))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(20, w//20))))
    return base


def background(size: tuple[int, int]) -> Image.Image:
    return _background_base(size).copy()


@lru_cache(maxsize=4)
def board_template(square: int) -> Image.Image:
    pad = max(10, square // 12)
    total = square + 2 * pad
    im = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(shadow)
    d.rounded_rectangle((3, 8, total-2, total-1), radius=max(6, pad//2), fill=(0, 0, 0, 180))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(2, square//100))))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, total-1, total-1), radius=max(6, pad//2), fill=(90,57,31,255), outline=(212,164,89,255), width=max(2, square//300))
    d.rectangle((pad//4,pad//4,total-pad//4-1,total-pad//4-1), fill=(155,104,54,255), outline=(51,37,27,255), width=2)
    s = square / 8
    for rank in range(8):
        for file in range(8):
            x0=pad+round(file*s); y0=pad+round(rank*s); x1=pad+round((file+1)*s); y1=pad+round((rank+1)*s)
            d.rectangle((x0,y0,x1-1,y1-1), fill=(235,236,208,255) if (rank+file)%2==0 else (115,149,82,255))
    small=font(max(12, square//65), False)
    for f in range(8):
        d.text((int(pad+(f+.85)*s),int(pad+7.76*s)),chr(97+f),font=small,fill=(235,236,208,220) if (f+7)%2 else (115,149,82,230),anchor="mm")
    for r in range(8):
        d.text((int(pad+.16*s),int(pad+(r+.15)*s)),str(8-r),font=small,fill=(115,149,82,240) if r%2==0 else (235,236,208,240),anchor="mm")
    return im


@lru_cache(maxsize=64)
def scaled_piece(code: str, height: int) -> Image.Image:
    source = PIECES[code]
    width = max(1, round(source.width * height / source.height))
    return source.resize((width, height), Image.Resampling.LANCZOS)


def draw_piece(board_img: Image.Image, piece: chess.Piece, file: int, rank_from_top: int, pad: int, square: int) -> None:
    s = square / 8
    code = ("w" if piece.color else "b") + piece.symbol().upper()
    height = int(s * .88)
    sprite = scaled_piece(code, height)
    width = sprite.width
    board_img.alpha_composite(sprite, (pad + int(file*s) + (int(s)-width)//2, pad + int(rank_from_top*s) + (int(s)-height)//2 + int(s*.02)))


def frame_at(mode: str, title: str, states: list[chess.Board], moves: list[chess.Move], sans: list[str], mate: bool,
             t: float, duration: float, final_time: float) -> Image.Image:
    short = mode == "puzzle_short"
    W,H = (1080,1920) if short else (1920,1080)
    square = 920 if short else 790
    template = board_template(square).copy()
    x = (W-template.width)//2 if short else 60
    y = 430 if short else (H-template.height)//2
    frame = background((W,H))
    d=ImageDraw.Draw(frame); gold=(246,177,63,255); white=(244,246,239,255); muted=(197,205,201,255)
    label = title.strip()
    size=47
    maxw=W-120 if short else W-(x+template.width+90)
    while d.textbbox((0,0),label,font=font(size))[2] > maxw and size>22:
        size-=2
    if short:
        d.rounded_rectangle((64,55,W-64,140),radius=24,fill=(9,13,17,220),outline=(246,177,63,130),width=2)
        d.text((W//2,97),label,font=font(size),fill=white,anchor="mm")
    else:
        d.text((x+template.width+55,70),label,font=font(size),fill=white)
        d.text((x+template.width+58,130),"CHESS BITS  •  ANALYSIS",font=font(24),fill=gold)
    reveal_start=1.0 if short else 1.5
    reveal_end=max(reveal_start+.2,final_time)
    if t < reveal_start:
        idx=-1; move=None; prog=None; state=states[0]
    elif t < reveal_end:
        span=(reveal_end-reveal_start)/len(moves)
        idx=min(len(moves)-1,int((t-reveal_start)/span)); local=((t-reveal_start)-idx*span)/span
        if local < .28:
            move=moves[idx]; prog=local/.28; state=states[idx]
        else:
            move=None; prog=None; state=states[idx+1]
    else:
        idx=len(moves)-1; move=None; prog=None; state=states[-1]
    if short:
        status="FIND THE TACTIC" if t<reveal_start else ("CHECKMATE" if mate and t>=reveal_end else "SOLUTION REVEAL")
        d.text((W//2,177),status,font=font(29),fill=gold,anchor="mt")
        move_lbl="Study the position" if idx<0 else f"Move {idx+1} of {len(moves)}"
        d.text((W//2,224),move_lbl,font=font(24,False),fill=muted,anchor="mt")
    else:
        status="CHECKMATE CONFIRMED" if mate and t>=reveal_end else ("FINAL POSITION" if t>=reveal_end else "PLAY THROUGH THE LINE")
        d.text((x+template.width+58,188),status,font=font(27),fill=white)
        if idx>=0:
            lines=[]
            for j in range(max(0,idx-15),idx+1):
                if j%2==0: lines.append(f"{j//2+1}. {sans[j]}")
                elif lines: lines[-1]+="  "+sans[j]
                else: lines.append(f"{j//2+1}... {sans[j]}")
            yy=250
            for line in lines[-11:]:
                d.text((x+template.width+58,yy),line,font=font(22,False),fill=muted); yy+=32
    pad=(template.width-square)//2
    if move is not None and prog is not None:
        overlay=Image.new("RGBA",template.size,(0,0,0,0)); od=ImageDraw.Draw(overlay); s=square/8
        for sq in (move.from_square,move.to_square):
            f=chess.square_file(sq); r=7-chess.square_rank(sq)
            od.rectangle((pad+int(f*s),pad+int(r*s),pad+int((f+1)*s)-1,pad+int((r+1)*s)-1),fill=(246,177,63,65))
        template.alpha_composite(overlay)
    for sq,piece in state.piece_map().items():
        if move is not None and prog is not None and sq in (move.from_square,move.to_square):
            continue
        f=chess.square_file(sq); r=7-chess.square_rank(sq)
        draw_piece(template,piece,f,r,pad,square)
    if move is not None and prog is not None:
        moving=state.piece_at(move.from_square)
        if moving:
            f0=chess.square_file(move.from_square); r0=7-chess.square_rank(move.from_square)
            f1=chess.square_file(move.to_square); r1=7-chess.square_rank(move.to_square)
            eased=prog*prog*(3-2*prog); s=square/8
            code=("w" if moving.color else "b")+moving.symbol().upper()
            h=int(s*.88); sprite=scaled_piece(code,h); w=sprite.width
            px=int(pad+(f0+(f1-f0)*eased)*s+(s-w)//2); py=int(pad+(r0+(r1-r0)*eased)*s+(s-h)//2+s*.02)
            template.alpha_composite(sprite,(px,py))
        if state.is_castling(move):
            rf=7 if chess.square_file(move.to_square)==6 else 0
            rt=5 if rf==7 else 3
            rook=state.piece_at(chess.square(rf,chess.square_rank(move.from_square)))
            if rook:
                f0=rf; r0=7-chess.square_rank(move.from_square); f1=rt; r1=r0; e=prog*prog*(3-2*prog); s=square/8
                h=int(s*.88); spr=scaled_piece(("w" if rook.color else "b")+"R",h); w=spr.width
                template.alpha_composite(spr,(int(pad+(f0+(f1-f0)*e)*s+(s-w)//2),int(pad+r0*s+(s-h)//2+s*.02)))
    frame.alpha_composite(template,(x,y))
    return frame.convert("RGB")


def render(job_id: str, spec: RenderRequest) -> dict:
    LOG.info("RENDER_START job_id=%s type=%s title=%s", job_id, spec.video_type, spec.title)
    job_dir=JOBS_DIR/job_id
    job_dir.mkdir(parents=True,exist_ok=False)
    for u in spec.voiceover_urls: validate_url(u)
    if spec.music_url: validate_url(spec.music_url)
    states,moves,sans,mate=parse_pgn(spec.pgn,spec.require_checkmate or spec.video_type=="puzzle_short")
    audio,audio_meta=make_narration(spec.voiceover_urls,job_dir)
    LOG.info("NARRATION_READY job_id=%s duration_seconds=%.2f", job_id, audio_meta["duration"])
    music=None; music_meta=None
    if spec.music_url:
        LOG.info("MUSIC_DOWNLOAD_START job_id=%s", job_id)
        music=job_dir/"music.audio"; download_audio(spec.music_url,music,0); music_meta=probe_audio(music)
        LOG.info("MUSIC_READY job_id=%s duration_seconds=%.2f", job_id, music_meta["duration"])
    duration=audio_meta["duration"]
    final_hold=max(2.3 if mate else 1.5,duration*(.12 if spec.video_type=="puzzle_short" else .23))
    reveal_end=max(.5,duration-final_hold)
    W,H=(1080,1920) if spec.video_type=="puzzle_short" else (1920,1080)
    out_tmp=job_dir/"video_part.mp4"; out=job_dir/"video.mp4"
    if music:
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-filter_threads","1","-filter_complex_threads","1","-y","-thread_queue_size","2","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","pipe:0","-thread_queue_size","2","-i",str(audio),"-stream_loop","-1","-thread_queue_size","2","-i",str(music),"-filter_complex","[1:a]volume=1.0[v];[2:a]volume=0.14[m];[v][m]amix=inputs=2:duration=first:dropout_transition=2[a]","-map","0:v","-map","[a]","-t",f"{duration:.3f}","-c:v","libx264","-preset","ultrafast","-tune","zerolatency","-threads:v","1","-crf","21","-pix_fmt","yuv420p","-r","30","-fps_mode","cfr","-c:a","aac","-threads:a","1","-b:a","160k","-ar","48000","-movflags","+faststart",str(out_tmp)]
    else:
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","pipe:0","-thread_queue_size","2","-i",str(audio),"-map","0:v","-map","1:a","-t",f"{duration:.3f}","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p","-r","30","-fps_mode","cfr","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(out_tmp)]
    total_frames=max(1,math.ceil(duration*FPS))
    LOG.info("VIDEO_ENCODE_START job_id=%s frames=%d fps=%d resolution=%dx%d duration_seconds=%.2f", job_id, total_frames, FPS, W, H, duration)
    encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for n in range(total_frames):
            im=frame_at(spec.video_type,spec.title,states,moves,sans,mate,n/FPS,duration,reveal_end)
            encoder.stdin.write(np.asarray(im,dtype=np.uint8).tobytes())
            del im
            if n % (FPS * 5) == 0:
                LOG.info("VIDEO_FRAME_PROGRESS job_id=%s frame=%d total=%d", job_id, n, total_frames)
        encoder.stdin.close(); err=encoder.stderr.read().decode("utf-8","replace")
        if encoder.wait(timeout=1800)!=0: raise RuntimeError("FFmpeg encode failed: "+err[-900:])
    except Exception:
        if encoder.poll() is None: encoder.kill(); encoder.wait()
        raise
    out_tmp.replace(out)
    LOG.info("VIDEO_ENCODE_COMPLETE job_id=%s", job_id)
    info=json.loads(run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(out)],90).stdout)
    video=next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"),None)
    audio_stream=next((s for s in info.get("streams",[]) if s.get("codec_type")=="audio"),None)
    if not video or not audio_stream: raise RuntimeError("Output QA failed: video or audio stream missing")
    expected=(1080,1920) if spec.video_type=="puzzle_short" else (1920,1080)
    if (video.get("width"),video.get("height"))!=expected: raise RuntimeError("Output QA failed: unexpected resolution")
    out_duration=float(info.get("format",{}).get("duration") or 0)
    if abs(out_duration-duration)>1.2: raise RuntimeError("Output QA failed: output/narration duration mismatch")
    run(["ffmpeg","-v","error","-xerror","-i",str(out),"-f","null","-"],min(1800,max(120,int(duration*3))))
    sha=hashlib.sha256()
    with out.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): sha.update(block)
    return {"file":str(out),"duration_seconds":round(out_duration,2),"bytes":out.stat().st_size,"sha256":sha.hexdigest(),"width":expected[0],"height":expected[1],"video_codec":video.get("codec_name"),"audio_codec":audio_stream.get("codec_name"),"audio_segments":audio_meta["segments"],"checkmate_confirmed":mate,"plies":len(moves),"last_san":sans[-1],"music_included":bool(music),"music_duration_seconds":round(music_meta["duration"],2) if music_meta else None,"warnings":[] if music else ["No background music provided"]}


def signature(job: str, exp: int) -> str:
    return hmac.new(MEDIA_SECRET.encode(),f"{job}:{exp}".encode(),hashlib.sha256).hexdigest()


def set_job(job: str, **fields) -> None:
    with LOCK:
        if job in JOBS:
            JOBS[job].update(fields); JOBS[job]["updated_at"] = int(time.time())


def do_job(job: str, spec: RenderRequest, base: str) -> None:
    set_job(job,status="running",started_at=int(time.time()))
    try:
        result=render(job,spec); exp=int(time.time())+TTL
        root=PUBLIC_BASE_URL or base.rstrip("/")
        if not root.startswith("https://"): raise RuntimeError("PUBLIC_BASE_URL must use HTTPS")
        result["media_url"]=f"{root}/media/{job}.mp4?expires={exp}&sig={signature(job,exp)}"
        set_job(job,status="completed",result=result,completed_at=int(time.time()))
        LOG.info("CHESSBITS_RENDER_COMPLETED job_id=%s media_url=%s sha256=%s duration_seconds=%s", job, result["media_url"], result["sha256"], result["duration_seconds"])
    except Exception as exc:
        LOG.exception("Render job %s failed",job)
        set_job(job,status="failed",error=str(exc)[:800],failed_at=int(time.time()))


def auth(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN: raise HTTPException(503,"CHESSBITS_API_TOKEN is not configured")
    if not authorization or not hmac.compare_digest(authorization,"Bearer "+API_TOKEN): raise HTTPException(401,"Unauthorized")


@app.on_event("startup")
def startup() -> None:
    DATA.mkdir(parents=True,exist_ok=True); JOBS_DIR.mkdir(parents=True,exist_ok=True)
    try: load_pieces(); LOG.info("Loaded %d Chess.com Neo sprites",len(PIECES))
    except Exception: LOG.exception("Failed to load chess piece sprites")
    # Explicit one-shot deployment hook; leave unset during normal service operation.
    raw = os.getenv("CHESSBITS_STARTUP_RENDER_JSON", "").strip()
    if raw:
        try:
            spec = RenderRequest.model_validate_json(raw)
            for url in spec.voiceover_urls: validate_url(url)
            if spec.music_url: validate_url(spec.music_url)
            parse_pgn(spec.pgn, spec.require_checkmate or spec.video_type == "puzzle_short")
            job = uuid.uuid4().hex
            with LOCK:
                JOBS[job] = {"job_id": job, "status": "queued", "created_at": int(time.time()), "video_type": spec.video_type, "title": spec.title}
            LOG.info("CHESSBITS_STARTUP_RENDER_QUEUED job_id=%s title=%s", job, spec.title)
            threading.Thread(target=do_job, args=(job, spec, PUBLIC_BASE_URL), daemon=True).start()
        except Exception:
            LOG.exception("CHESSBITS_STARTUP_RENDER_REJECTED")


@app.get("/health")
def health() -> dict:
    ready=bool(API_TOKEN and MEDIA_SECRET and len(PIECES)==12 and shutil.which("ffmpeg") and shutil.which("ffprobe"))
    return {"service":"Chess Bits Cloud Worker","version":"0.1.0","status":"ready" if ready else "degraded","ffmpeg":bool(shutil.which("ffmpeg")),"ffprobe":bool(shutil.which("ffprobe")),"piece_assets_loaded":len(PIECES)==12,"render_endpoint_ready":ready}


@app.post("/v1/jobs/render",status_code=202,dependencies=[Depends(auth)])
def create_job(spec: RenderRequest, tasks: BackgroundTasks, req: Request) -> dict:
    for u in spec.voiceover_urls: validate_url(u)
    if spec.music_url: validate_url(spec.music_url)
    parse_pgn(spec.pgn,spec.require_checkmate or spec.video_type=="puzzle_short")
    job=uuid.uuid4().hex
    with LOCK: JOBS[job]={"job_id":job,"status":"queued","created_at":int(time.time()),"video_type":spec.video_type,"title":spec.title}
    host=req.headers.get("x-forwarded-host") or req.headers.get("host") or ""
    proto=req.headers.get("x-forwarded-proto","https").split(",")[0].strip()
    base=PUBLIC_BASE_URL or f"{proto}://{host}"
    tasks.add_task(do_job,job,spec,base)
    return {"job_id":job,"status":"queued","status_url":f"{base}/v1/jobs/{job}","note":"Poll until completed. Require music_included=true before publishing when background music is mandatory."}


@app.get("/v1/jobs/{job}",dependencies=[Depends(auth)])
def status(job: str) -> dict:
    with LOCK: item=JOBS.get(job)
    if not item: raise HTTPException(404,"Job not found on this worker instance")
    result={k:v for k,v in item.items() if k!="result"}
    if item.get("result"):
        data=dict(item["result"]); data.pop("file",None); result["result"]=data
    return result


@app.get("/media/{job}.mp4")
def media(job: str, expires: int, sig: str):
    if not MEDIA_SECRET: raise HTTPException(503,"Media signing is not configured")
    if not re.fullmatch(r"[0-9a-f]{32}",job): raise HTTPException(404,"Media not found")
    now=int(time.time())
    if expires<now or expires>now+21600 or not hmac.compare_digest(sig,signature(job,expires)): raise HTTPException(403,"Media URL expired or invalid")
    path=JOBS_DIR/job/"video.mp4"
    if not path.is_file(): raise HTTPException(404,"Media no longer available")
    return FileResponse(path,media_type="video/mp4",filename=f"chess-bits-{job}.mp4",headers={"Cache-Control":"private, max-age=60","X-Content-Type-Options":"nosniff"})
