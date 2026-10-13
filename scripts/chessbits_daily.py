#!/usr/bin/env python3
"""Free, self-healing daily Chess Bits publisher.

Uses the repository's approved Neo renderer, free Edge TTS, Lichess's public
daily puzzle endpoint, NCS tracks for puzzle Shorts only, and the official
YouTube Data API. Long-form voiceovers intentionally have no background music.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import smtplib
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import chess
import chess.pgn
import numpy as np
import requests
import edge_tts
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud-worker"))
import app as renderer  # noqa: E402 - reuses the approved Neo visual template

TZ = ZoneInfo("Asia/Kolkata")
CHANNEL_ID = "UCREAxtRG8ECVn0xQKbwZiFw"
STATE_PATH = ROOT / "state" / "published.json"
OUT_DIR = ROOT / "output"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
MUSIC = [
    {
        "id": "ncs-free",
        "url": "https://ncs.io/track/download/e129ae98-f110-496c-8490-5dd339f63914",
        "credit": "Song: Elektronomia & JJD - Free [NCS Release]\nMusic provided by NoCopyrightSounds\nFree Download/Stream: https://ncs.io/Free\nWatch: https://youtu.be/9Va88Kt0NN0",
    },
    {
        "id": "ncs-done",
        "url": "https://ncs.io/track/download/e995ef22-aa2f-4afb-a48d-ed738c69a062",
        "credit": "Song: Clarx - Done (feat. Halvorsen) [NCS Release]\nMusic provided by NoCopyrightSounds\nFree Download/Stream: https://ncs.io/Done\nWatch: https://youtu.be/MBN5HN3o7FE",
    },
    {
        "id": "ncs-online",
        "url": "https://ncs.io/track/download/f80763c7-9f37-4ea5-92e3-66b47f665656",
        "credit": "Song: MANSHN - Online [Arcade Release]\nMusic provided by NoCopyrightSounds\nFree Download/Stream: https://ncs.io/Online",
    },
]

OPENINGS = [
    {
        "id": "scotch-gambit",
        "title": "Scotch Gambit: Fast Development and Attacking Ideas",
        "opening": "the Scotch Gambit",
        "moves": "1. e4 e5 2. Nf3 Nc6 3. d4 exd4 4. Bc4 Nf6 5. e5 d5 6. Bb5 Ne4 7. Nxd4 Bd7 8. Bxc6 bxc6 9. O-O Bc5 10. Be3 O-O 11. f3 Ng5 12. Nc3 Ne6 13. Nce2 Bb6 14. Kh1 a5 15. Nf5 d4 16. Bd2 Nf4 17. Nfg3 Nd5 18. f4 f5",
        "hook": "The Scotch Gambit is a practical choice for players who want open lines, fast development, and initiative rather than a slow manoeuvring game. White gives up the central pawn temporarily to develop the bishop actively and make Black solve concrete problems early.",
        "ideas": "The first strategic test is whether White can use the lead in development before Black completes development and consolidates the extra pawn. The bishop on c4 targets the sensitive f7-square, while the e-pawn advance can gain space and disrupt Black's natural development. Black's d-pawn counterstrike is important: a gambit is not a promise of an attack, but a trade of material for time and activity.",
        "plan": "White should develop with tempo, castle, and bring the rooks toward open or semi-open files. Knights should support central squares and avoid repeated moves that allow Black to catch up. Black should challenge the centre, exchange attacking pieces when favourable, and avoid spending too many tempi chasing pawns. The right plan depends on the position rather than the opening name alone.",
        "mistake": "The common mistake for White is to attack before enough pieces are ready, or to keep sacrificing without a concrete follow-up. The common mistake for Black is to cling to every pawn while falling behind in development. Either side should count attackers and defenders around the king before committing to a forcing line.",
        "exercise": "Pause after the opening moves and ask three questions: which side is ahead in development, which central break changes the position, and which piece is currently least active? Find a useful improving move before searching for a tactical blow. That habit makes gambit positions easier to evaluate over the board.",
    },
    {
        "id": "evans-gambit",
        "title": "Evans Gambit: Open Lines Against the Italian Game",
        "opening": "the Evans Gambit",
        "moves": "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4 exd4 7. O-O dxc3 8. Qb3 Qf6 9. e5 Qg6 10. Nxc3 Nge7 11. Ba3 O-O 12. Rad1",
        "hook": "The Evans Gambit begins with a pawn offer on b4 to gain tempi against Black's bishop and build a powerful centre. It is one of the clearest examples of how a small material investment can create a lasting initiative.",
        "ideas": "After the bishop accepts the pawn, White gains time with c3 and d4. That central expansion opens diagonals and makes Black's king safety more urgent. The queen can join the attack on the kingside while the light-squared bishop seeks an active diagonal. Black can defend, but must coordinate pieces rather than collect pawns automatically.",
        "plan": "White should use the open centre to develop quickly, castle, and place a rook on the d-file. The bishop pair and active queen matter more than the pawn count in the short term. Black should return material when necessary to complete development, trade attacking pieces, and keep the centre under control.",
        "mistake": "White should not launch an attack with only the queen and one bishop; the remaining pieces need to join. Black should not play passive pawn moves while the centre is opening. In either case, a useful tempo gained by attacking a piece is valuable only if the attacking piece can improve afterward.",
        "exercise": "Replay the position after White's c3 and d4. Identify which files and diagonals opened, then choose the piece that can use them first. Compare a move that develops with tempo against a pawn grab. In gambits, development is a resource that must be converted before it disappears.",
    },
    {
        "id": "danish-gambit",
        "title": "Danish Gambit: Development for Two Pawns",
        "opening": "the Danish Gambit",
        "moves": "1. e4 e5 2. d4 exd4 3. c3 dxc3 4. Bc4 cxb2 5. Bxb2 d5 6. Bxd5 Nf6 7. Nc3 Bb4 8. Qb3 Nxd5 9. exd5 Qe7+ 10. Ne2 O-O 11. O-O",
        "hook": "The Danish Gambit is a direct bargain: White offers central pawns to develop the bishops quickly and obtain open lines. The opening rewards activity, but it also punishes an attack that runs out of pieces.",
        "ideas": "The bishops become active early and White can develop with threats while Black spends time collecting material. The key question is whether the open diagonals and rapid castling give White enough compensation. Black's most reliable approach is usually to simplify when possible and finish development without allowing a direct attack on the king.",
        "plan": "White should develop the knights, castle, and keep central files open while bringing a rook into play. The queen's activity should support threats rather than become a target. Black should return a pawn if doing so frees the position, and should calculate checks carefully before grabbing more material.",
        "mistake": "A frequent error is to treat the gambit as an automatic attack. If White trades away active pieces without gaining something concrete, the material deficit becomes more important. Black can also go wrong by moving the same piece repeatedly while White's bishops and rooks take over the centre.",
        "exercise": "After each forcing move, compare the number of developed pieces and the safety of both kings. If no direct tactic exists, improve the least active piece. This gives a realistic measure of compensation instead of relying on the opening's reputation.",
    },
    {
        "id": "kings-gambit",
        "title": "King's Gambit: Initiative and King Safety",
        "opening": "the King's Gambit",
        "moves": "1. e4 e5 2. f4 exf4 3. Nf3 g5 4. h4 g4 5. Ne5 Nf6 6. Bc4 d5 7. exd5 Bd6 8. d4 Nh5 9. O-O Qxh4 10. Bxf4 Nxf4 11. Rxf4 Bxe5 12. dxe5",
        "hook": "The King's Gambit deliberately changes the pawn structure to gain attacking chances and rapid development. It can create sharp play, but both sides need to respect king safety and calculate accurately.",
        "ideas": "White's f-pawn offer removes Black's e-pawn and invites open lines. Black can accept the pawn, but the kingside pawn moves may create targets and cost tempi. White's central development and bishop activity can create threats, while Black's extra material matters only if the king survives and pieces coordinate.",
        "plan": "White should develop quickly, use the centre, and avoid making extra pawn moves without a reason. Black should complete development and decide whether to return material to reduce the attack. The correct plan comes from piece placement and king safety rather than the fact that one side has won a pawn.",
        "mistake": "White should not push every kingside pawn just because the position looks attacking. Black should not automatically hold the extra pawn if it leaves the king exposed. Check forcing moves first: checks, captures, and direct threats often determine whether an initiative is real.",
        "exercise": "Pause before every pawn push and name the square it weakens. Then look for a developing move that creates a threat. This simple discipline helps both sides handle sharp openings without turning a promising position into a series of speculative attacks.",
    },
    {
        "id": "vienna-gambit",
        "title": "Vienna Gambit: Build a Centre and Take Space",
        "opening": "the Vienna Gambit",
        "moves": "1. e4 e5 2. Nc3 Nf6 3. f4 d5 4. fxe5 Nxe4 5. Nf3 Be7 6. d3 Nxc3 7. bxc3 O-O 8. d4 c5 9. Bd3 Nc6 10. O-O",
        "hook": "The Vienna Gambit gives White a less familiar route into open-game positions. Instead of rushing into a direct attack, White tries to combine central space with active piece development.",
        "ideas": "The early f-pawn move supports e5 and changes the centre. Black's counterstrike with d5 is a key practical response, and White has to decide when to exchange pawns and when to maintain the centre. The structure can become open quickly, making development and king safety especially important.",
        "plan": "White should finish development, castle, and use the central pawns to limit Black's pieces. The bishop on d3 can support kingside ideas, but should not become a target. Black should challenge the centre with ...c5 or piece pressure, then use open lines instead of letting White keep space uncontested.",
        "mistake": "A common mistake is to chase an attack before the centre is stable. Another is to exchange central pawns without noticing which files open for the opponent. Always check the resulting pawn structure and identify which piece benefits from the exchange.",
        "exercise": "After the first central exchanges, evaluate space, development, and king safety separately. If White has more space but fewer developed pieces, complete development. If Black has equal development, challenge the centre before White can establish a bind.",
    },
    {
        "id": "smith-morra",
        "title": "Smith-Morra Gambit: Active Pieces Against the Sicilian",
        "opening": "the Smith-Morra Gambit",
        "moves": "1. e4 c5 2. d4 cxd4 3. c3 dxc3 4. Nxc3 Nc6 5. Nf3 d6 6. Bc4 e6 7. O-O Nf6 8. Qe2 Be7 9. Rd1 e5 10. h3 O-O 11. Bg5 Be6 12. Bxf6 Bxf6 13. Nd5 Rc8 14. Rac1",
        "hook": "The Smith-Morra Gambit is a practical way to meet the Sicilian with rapid development and open files. White gives a pawn to get pieces onto useful squares without spending several moves on slow manoeuvring.",
        "ideas": "The knight recapture on c3 develops a piece and keeps pressure on the centre. White's bishop and queen can coordinate with the rooks along central files. Black's setup is sound when the pieces work together and the centre remains controlled; Black should not confuse holding the pawn with solving every positional problem.",
        "plan": "White should castle, use the d-file, and look for central outposts. Black should finish development, exchange a few active pieces when convenient, and prevent a knight from settling on a strong central square. Both sides must be alert to tactics around e5 and d5.",
        "mistake": "White can overestimate the attack and sacrifice additional material without a concrete target. Black can become passive and allow White's pieces to dominate. When deciding whether to accept a gambit, ask how easily the extra pawn can be held and how many tempi the defender has spent collecting it.",
        "exercise": "Study the central squares d5 and e5 after development is complete. Which side can occupy them, challenge them, or use them as a route for a knight? Positional advantages in gambit openings often begin with a small improvement in piece activity.",
    },
    {
        "id": "benko-gambit",
        "title": "Benko Gambit: Long-Term Pressure on the Queenside",
        "opening": "the Benko Gambit",
        "moves": "1. d4 Nf6 2. c4 c5 3. d5 b5 4. cxb5 a6 5. bxa6 Bxa6 6. Nc3 d6 7. e4 Bxf1 8. Kxf1 g6 9. g3 Bg7 10. Kg2 O-O 11. Nf3 Nbd7 12. Re1 Qa5",
        "hook": "The Benko Gambit is different from a direct kingside attack. Black gives a pawn to obtain lasting pressure on the queenside files and diagonals, often aiming for activity deep into the middlegame.",
        "ideas": "Black's bishop recapture opens the a-file and helps the rook enter the game. The pressure may not produce an immediate tactic, but it can make White spend moves defending pawns and squares. White's central space is the principal counterweight, so the game often becomes a contest between central control and queenside pressure.",
        "plan": "Black should coordinate the rooks and queen on open files, keep pieces active, and avoid trading away all sources of pressure without compensation. White should develop carefully, support the centre, and consider returning a pawn if that reduces Black's activity. Space is useful when it can be converted into a stable advantage.",
        "mistake": "Black should not expect the gambit pawn to be won back immediately. White should not defend every pawn with passive pieces if doing so gives Black open files for free. Look for a central break that changes the balance before the pressure becomes permanent.",
        "exercise": "Trace the open and semi-open files on the queenside, then identify which rook can use them first. Next, identify White's most useful central break. This reveals the strategic battle even when neither side has a forcing combination.",
    },
    {
        "id": "blackmar-diemer",
        "title": "Blackmar-Diemer Gambit: Open Lines and Fast Development",
        "opening": "the Blackmar-Diemer Gambit",
        "moves": "1. d4 d5 2. e4 dxe4 3. Nc3 Nf6 4. f3 exf3 5. Nxf3 g6 6. Bc4 Bg7 7. O-O Nc6 8. Qe1 Bg4 9. Bg5 Qd7 10. Qg3",
        "hook": "The Blackmar-Diemer Gambit trades a central pawn for open lines, rapid development, and attacking chances. White must use the lead in development before Black finishes coordinating the pieces.",
        "ideas": "White's f-pawn offer opens the f-file and brings a knight into the centre. The bishop on c4 and queen can point toward the kingside, but the attack depends on development and concrete threats. Black's best defence is to return material when useful, complete development, and avoid allowing every white piece to enter with tempo.",
        "plan": "White should castle, develop the bishops actively, and bring a rook to an open file. Black should challenge the centre, exchange active attacking pieces if possible, and avoid moving the same piece repeatedly while the king remains in the centre.",
        "mistake": "White should not sacrifice more material automatically once the first pawn has been offered. Black should not attempt to preserve every pawn if doing so costs several tempi. The compensation must be assessed from activity, king safety, and the resulting position.",
        "exercise": "After the first central exchanges, identify White's most active piece and Black's easiest developing move. Compare the attacking chances with the material count, then decide what White must do before Black completes development."
    },
    {
        "id": "latvian-gambit",
        "title": "Latvian Gambit: A Sharp Counterattack After 1.e4 e5",
        "opening": "the Latvian Gambit",
        "moves": "1. e4 e5 2. Nf3 f5 3. Nxe5 Qf6 4. d4 d6 5. Nc4 fxe4 6. Nc3 Qg6 7. Ne3 Nf6 8. g3",
        "hook": "The Latvian Gambit is one of the sharpest ways to challenge White's king-knight opening. Black offers a pawn early to open lines and generate activity, but the position demands accurate calculation from both sides.",
        "ideas": "After ...f5, Black attacks the centre and invites White to take the e-pawn. The queen move to f6 adds pressure, while ...d6 attacks the advanced knight. Black must balance initiative with king safety; White can often gain an advantage by developing calmly and returning material if that neutralizes the attack.",
        "plan": "White should develop without chasing every pawn and keep an eye on Black's queen and kingside. Black should develop quickly, create forcing threats, and avoid spending too many tempi on speculative queen moves. Both sides must calculate checks, captures, and direct threats before launching an attack.",
        "mistake": "The main mistake for Black is treating the gambit as automatic compensation. If White consolidates, the missing pawn can matter. White can also go wrong by trying to refute the opening with a single tactical idea instead of completing development.",
        "exercise": "Replay the first six moves and pause after the queen reaches f6. Count the developed pieces and list each side's forcing moves. Decide whether White should attack the queen, improve a piece, or secure the centre."
    },
    {
        "id": "albin-countergambit",
        "title": "Albin Countergambit: Challenge the Queen's Pawn Centre",
        "opening": "the Albin Countergambit",
        "moves": "1. d4 d5 2. c4 e5 3. dxe5 d4 4. Nf3 Nc6 5. g3 Be6 6. Nbd2 Qd7 7. Bg2 O-O-O 8. O-O h5 9. Ng5 Bf5 10. Nde4 h4",
        "hook": "The Albin Countergambit is a direct challenge to the Queen's Gambit. Black gives up a pawn to push a dangerous advanced pawn into White's position and create tactical opportunities.",
        "ideas": "The early ...e5 offer aims to open lines and establish the d-pawn on d4. White can try to blockade that pawn and develop around it, while Black seeks active pieces and pressure before White consolidates. The advanced pawn is useful only if it is supported by piece activity.",
        "plan": "Black should support the advanced pawn, finish development, and use the open diagonals. White should challenge the pawn when the pieces are ready, keep the king safe, and avoid allowing a central pawn to cramp the position indefinitely.",
        "mistake": "Black should not push the passed pawn without bringing pieces into play. White should not waste tempi chasing it if a stable blockade is available. A sound plan should improve development as well as address the pawn structure.",
        "exercise": "Look at the advanced d-pawn and identify which white pieces can blockade it. Then find Black's most useful developing move. Compare a direct pawn push with a move that increases support behind the pawn."
    },
    {
        "id": "budapest-gambit",
        "title": "Budapest Gambit: Active Development Against 1.d4",
        "opening": "the Budapest Gambit",
        "moves": "1. d4 Nf6 2. c4 e5 3. dxe5 Ng4 4. Nf3 Nc6 5. Bf4 Bb4+ 6. Nbd2 Qe7 7. e3 Ngxe5 8. Nxe5 Nxe5 9. Be2 d6 10. O-O O-O 11. a3 Bxd2 12. Qxd2",
        "hook": "The Budapest Gambit gives Black immediate activity against White's central pawn. Black seeks rapid development and active piece play instead of passively trying to recover the pawn.",
        "ideas": "The pressure on e5 forces White to make decisions early. Black can use checks and pins to develop with tempo, but the initiative must be maintained through sound piece placement. White can often return the pawn or exchange pieces to reach a stable position with a space advantage.",
        "plan": "Black should develop the remaining pieces and aim to make the e-pawn or central squares a source of pressure. White should complete development, connect the rooks, and avoid spending too many moves protecting a pawn if the pieces are not ready. Both sides should check tactics before exchanging the active knights.",
        "mistake": "Black should not confuse a quick check with lasting initiative; after each forcing move, determine the follow-up. White should not choose a passive defence that leaves the pieces stuck. The central pawn is one factor, but development and king safety decide the compensation.",
        "exercise": "After the early exchanges, evaluate whether Black still has active threats or whether White has consolidated. Choose one move for each side that improves the least active piece. That is the practical decision that often matters more than memorizing the gambit name.",
    },
    {
        "id": "elephant-gambit",
        "title": "Elephant Gambit: Counterattack in the Centre",
        "opening": "the Elephant Gambit",
        "moves": "1. e4 e5 2. Nf3 d5 3. exd5 e4 4. Qe2 Nf6 5. d3 Qxd5 6. dxe4 Nxe4 7. Nbd2 f5 8. g3 Bb4 9. Bg2 O-O 10. O-O",
        "hook": "The Elephant Gambit challenges White's development from the very first moves. Black offers central material to seize space and force White to solve concrete problems instead of building an unrestricted centre.",
        "ideas": "Black's ...d5 and ...e4 create immediate tension. The queen recapture on d5 brings material back but also exposes the queen to developing moves. Both sides have to balance central activity with the need to bring minor pieces into the game.",
        "plan": "Black should complete development, castle when safe, and use central pressure rather than rely on a single early attack. White should develop with tempo, secure the king, and be prepared to return material if it removes Black's initiative.",
        "mistake": "Black can go wrong by moving the queen repeatedly without creating a lasting threat. White can also lose time by trying to hold every pawn while the centre remains unstable. Calculate the forcing replies before committing to a tactical line.",
        "exercise": "After the queen exchange of central captures, list which pieces are developed and which king is safer. Find one move that improves a piece while creating a threat, then compare it with a speculative pawn push."
    },
    {
        "id": "staunton-gambit",
        "title": "Staunton Gambit: Active Play Against the Dutch Defence",
        "opening": "the Staunton Gambit",
        "moves": "1. d4 f5 2. e4 fxe4 3. Nc3 Nf6 4. Bg5 d5 5. f3 exf3 6. Qxf3 e6 7. Bd3 Be7 8. Nge2 O-O 9. O-O Nc6 10. Bxf6 Bxf6",
        "hook": "The Staunton Gambit meets the Dutch Defence with an early central pawn offer. White tries to use open lines and rapid development before Black's kingside structure settles.",
        "ideas": "White gives up the e-pawn to open the centre and gain active piece placement. The queen and bishops can develop quickly, but White must make the initiative count before Black consolidates. Black should return material when useful and use central control to reduce the attack.",
        "plan": "White should develop both knights, castle, and look for useful targets in the centre. Black should contest the centre, complete development, and avoid passive moves that allow White to coordinate the queen and bishops with tempo.",
        "mistake": "White should not assume that an open file guarantees an attack. Black should not defend passively or cling to every pawn if development falls behind. Count attackers and defenders before starting a forcing sequence.",
        "exercise": "Pause after White's f3 and calculate Black's best capture. Then follow how White's queen replaces the pawn and ask whether the open lines justify the material investment. Repeat the position from Black's side to practise defending against an initiative."
    },
]

def today_ist() -> date:
    return datetime.now(TZ).date()


def load_state() -> dict:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return {"published": []}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(value.get("published"), list):
            raise ValueError("published must be a list")
        return value
    except Exception as exc:
        raise RuntimeError(f"Publishing ledger is invalid; stopping safely: {exc}") from exc


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def next_target_date(state: dict) -> date | None:
    rows = state.get("published", [])
    if not rows:
        return today_ist()
    latest = max(date.fromisoformat(row["target_date"]) for row in rows)
    candidate = latest + timedelta(days=1)
    return candidate if candidate <= today_ist() else None


def next_kind(state: dict) -> str:
    rows = state.get("published", [])
    if not rows:
        return "opening"
    latest = max(rows, key=lambda row: row["target_date"])
    return "puzzle" if latest["kind"] == "opening" else "opening"


def marker_for(target: date) -> str:
    return "CB" + target.strftime("%Y%m%d")


def pgn_for_opening(entry: dict) -> str:
    return (
        f'[Event "Chess Bits Opening Lesson"]\n'
        f'[Site "Chess Bits"]\n[White "Chess Bits"]\n[Black "{entry["opening"]}"]\n'
        f'[Result "*"]\n[Opening "{entry["opening"]}"]\n\n{entry["moves"]} *\n'
    )


def validate_openings() -> None:
    seen = set()
    for entry in OPENINGS:
        if entry["id"] in seen:
            raise RuntimeError(f"Duplicate opening id: {entry['id']}")
        seen.add(entry["id"])
        states, moves, sans, mate = renderer.parse_pgn(pgn_for_opening(entry), False)
        if len(moves) < 12 or len(sans) != len(moves):
            raise RuntimeError(f"Opening line is too short or invalid: {entry['id']}")


def youtube_client():
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError(
            "Missing YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET or YOUTUBE_REFRESH_TOKEN GitHub secrets. "
            "Complete the one-time setup in README.md before enabling uploads."
        )
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(GoogleRequest())
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    response = service.channels().list(part="id,contentDetails", mine=True).execute()
    items = response.get("items", [])
    if len(items) != 1 or items[0].get("id") != CHANNEL_ID:
        found = items[0].get("id") if items else "none"
        raise RuntimeError(f"YouTube OAuth is connected to the wrong channel (found {found}); expected Chess Bits.")
    return service, items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def find_existing_upload(service, uploads_playlist: str, marker: str):
    page = service.playlistItems().list(
        part="contentDetails", playlistId=uploads_playlist, maxResults=50
    ).execute()
    ids = [item["contentDetails"]["videoId"] for item in page.get("items", [])]
    for offset in range(0, len(ids), 50):
        batch = ids[offset:offset + 50]
        if not batch:
            continue
        response = service.videos().list(part="snippet,status", id=",".join(batch)).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            if marker in (snippet.get("tags") or []):
                return {
                    "video_id": item["id"],
                    "title": snippet.get("title", ""),
                    "privacy": status.get("privacyStatus", ""),
                    "upload_status": status.get("uploadStatus", ""),
                    "tags": snippet.get("tags", []),
                }
    return None


def ensure_public(service, video_id: str) -> dict:
    """Verify that the newly requested public upload is actually public and processed."""
    for attempt in range(90):  # up to 15 minutes; scheduled retries resume by the stable video marker
        response = service.videos().list(
            part="snippet,status,processingDetails", id=video_id
        ).execute()
        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"YouTube did not return uploaded video {video_id}.")
        item = items[0]
        status = item.get("status", {})
        processing = item.get("processingDetails", {})
        processing_status = processing.get("processingStatus")
        upload_status = status.get("uploadStatus")
        if upload_status in ("failed", "rejected", "deleted"):
            reason = status.get("failureReason") or status.get("rejectionReason") or processing.get("processingFailureReason") or status
            raise RuntimeError(f"YouTube upload/processing failed for video {video_id}: {reason}")
        if processing_status == "failed":
            raise RuntimeError(
                f"YouTube processing failed for video {video_id}: {processing.get('processingFailureReason', 'unknown reason')}"
            )
        if status.get("privacyStatus") != "public":
            raise RuntimeError(
                "YouTube did not accept the requested public visibility. Check the YouTube API compliance audit "
                "and channel settings. For safety, the automation will not change the privacy of an existing video."
            )
        if upload_status == "processed" and processing_status == "succeeded":
            return item
        if attempt % 6 == 0:
            print(
                f"YOUTUBE_PROCESSING_WAIT video_id={video_id} attempt={attempt + 1}/90 "
                f"privacy={status.get('privacyStatus')} upload={upload_status} processing={processing_status}",
                flush=True,
            )
        time.sleep(10)
    raise RuntimeError(
        "YouTube has not confirmed successful processing within 15 minutes. "
        "The scheduled retry will resume by video marker instead of intentionally uploading a duplicate."
    )


def set_start_position_thumbnail(service, video_id: str, thumbnail_path: Path | None) -> bool:
    """Attempt to use the initial chess position as the video's custom thumbnail."""
    if not thumbnail_path or not thumbnail_path.is_file():
        print("THUMBNAIL_SKIPPED: start-position image unavailable.", flush=True)
        return False
    for attempt in range(3):
        try:
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg", resumable=False),
            ).execute()
            print(f"THUMBNAIL_SET video_id={video_id}", flush=True)
            return True
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            print(f"THUMBNAIL_SET_FAILED video_id={video_id} http_status={status}", flush=True)
            if status not in (408, 425, 429, 500, 502, 503, 504):
                return False
        except Exception as exc:
            print(f"THUMBNAIL_SET_RETRY video_id={video_id} attempt={attempt + 1} type={type(exc).__name__}", flush=True)
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    return False


def publish_video(service, uploads_playlist: str, video_path: Path, title: str, description: str,
                  tags: list[str], target: date, short: bool, thumbnail_path: Path | None = None) -> tuple[str, dict, bool]:
    marker = marker_for(target)
    existing = find_existing_upload(service, uploads_playlist, marker)
    if existing:
        if existing["upload_status"] in ("failed", "rejected", "deleted"):
            raise RuntimeError(
                f"A previous upload for {target.isoformat()} exists but YouTube marked it {existing['upload_status']}; "
                "stopping to avoid duplicate public videos."
            )
        item = ensure_public(service, existing["video_id"])
        # Existing uploads are never edited; thumbnail-setting happens only on fresh inserts.
        return existing["video_id"], item, False

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": list(dict.fromkeys((tags + [marker]))),
            "categoryId": "27",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    last_error = None
    for attempt in range(3):
        try:
            media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
            request = service.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=3)
            video_id = response.get("id")
            if not video_id:
                raise RuntimeError("YouTube upload completed without returning a video id.")
            # Thumbnail is part of creating this fresh upload, not a repair to older channel content.
            thumbnail_set = set_start_position_thumbnail(service, video_id, thumbnail_path)
            verified = ensure_public(service, video_id)
            return video_id, verified, thumbnail_set
        except Exception as exc:
            last_error = exc
            # Before a new attempt, detect whether YouTube accepted the upload before the connection failed.
            try:
                existing = find_existing_upload(service, uploads_playlist, marker)
                if existing and existing["upload_status"] not in ("failed", "rejected", "deleted"):
                    if existing.get("privacy") != "public":
                        raise RuntimeError(
                            f"YouTube already accepted video {existing['video_id']} but it is not public. "
                            "Refusing to upload a duplicate; check the YouTube API compliance audit."
                        ) from exc
                    try:
                        item = ensure_public(service, existing["video_id"])
                    except Exception as verify_exc:
                        raise RuntimeError(
                            f"YouTube already accepted video {existing['video_id']} for this date, but processing/public "
                            "verification is incomplete. Refusing to upload a duplicate; the next scheduled run will resume."
                        ) from verify_exc
                    return existing["video_id"], item, False
            except RuntimeError:
                raise
            except Exception:
                # No accepted video was found; only then is a fresh upload retry safe.
                pass
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"YouTube upload failed after three attempts: {type(last_error).__name__}: {last_error}")


def run_checked(command: list[str], timeout: int = 900, log_path: Path | None = None):
    if log_path:
        with log_path.open("wb") as stream:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=stream, timeout=timeout)
        stderr = log_path.read_text(errors="replace")[-1500:] if log_path.exists() else ""
        if result.returncode:
            raise RuntimeError(f"{Path(command[0]).name} failed: {stderr}")
        return result.stdout
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed: {result.stderr.decode('utf-8', 'replace')[-1500:]}")
    return result.stdout


def probe_audio(path: Path) -> float:
    data = json.loads(run_checked(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], 90))
    if not any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])):
        raise RuntimeError(f"Audio stream missing from {path.name}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0 or duration > 900:
        raise RuntimeError(f"Unexpected audio duration in {path.name}: {duration}")
    run_checked(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], min(900, max(60, int(duration * 2))))
    return duration


async def create_voiceover(text: str, target_path: Path) -> None:
    failures = []
    for voice in ("en-US-AndrewNeural", "en-US-GuyNeural", "en-US-BrianNeural"):
        try:
            target_path.unlink(missing_ok=True)
            communicate = edge_tts.Communicate(text, voice=voice, rate="-4%", volume="+0%")
            await communicate.save(str(target_path))
            if target_path.exists() and target_path.stat().st_size > 1024:
                print(f"TTS_READY voice={voice} bytes={target_path.stat().st_size}", flush=True)
                return
            raise RuntimeError("TTS returned an empty audio file")
        except Exception as exc:
            failures.append(f"{voice}:{type(exc).__name__}")
            time.sleep(2)
    raise RuntimeError("All free TTS voices failed: " + ", ".join(failures))


def make_opening_script(entry: dict, sans: list[str]) -> str:
    line = ", ".join(sans[:12])
    return f"""
Welcome back to Chess Bits. Today we are studying {entry['opening']}, with a practical example designed to show how the opening plan becomes a middlegame plan. The goal is not to memorise a long string of moves. The goal is to understand what each side is trying to achieve, so you can find useful moves even when your opponent leaves the book.

{entry['hook']}

Here is the strategic idea to keep in mind. {entry['ideas']}

Follow this sample line on the board: {line}. Do not treat the notation as a race to reach a familiar position. After every move, ask which squares have become weaker, which pieces have improved, and which pawn break can change the position. A good opening move normally develops a piece, contests the centre, improves king safety, or creates a concrete threat. When it does none of these things, ask why it is necessary.

For a practical plan, remember this. {entry['plan']}

Now consider the mistakes. {entry['mistake']}

Use a simple calculation routine before you move. First look for checks, captures, and direct threats for both sides. Then check whether a proposed move leaves a piece undefended or opens a line toward your king. Finally, compare the least active piece on each side. If there is no forcing continuation, improving that piece is often better than making a speculative pawn push.

Here is your training exercise. {entry['exercise']}

When you review the game, pause at the first moment the centre changes. Predict the next move before revealing it, and explain the reason in one sentence. Repeat the exercise from the other side of the board. This is how opening knowledge turns into practical calculation.

Thanks for watching Chess Bits. Save this lesson for your next training session, and focus on the plan behind the moves rather than memorising them blindly. Play carefully, calculate forcing moves first, and keep improving one decision at a time.
""".strip()


def fetch_puzzle(target: date, used_ids: set[str]) -> tuple[str, dict, list[str], str]:
    """Select a genuinely new, difficult recent daily puzzle with bounded source fallback."""
    failures = []
    for offset in range(0, 15):
        puzzle_date = target - timedelta(days=offset)
        url = "https://lichess.org/api/puzzle/daily?date=" + puzzle_date.strftime("%Y%m%d")
        try:
            response = requests.get(url, timeout=(15, 45), headers={"User-Agent": "ChessBitsAutoPublisher/1.0"})
            response.raise_for_status()
            data = response.json()
            puzzle = data.get("puzzle", {})
            game_data = data.get("game", {})
            puzzle_id = str(puzzle.get("id", ""))
            if not puzzle_id or puzzle_id in used_ids:
                failures.append(f"{puzzle_date}:missing-or-used")
                continue
            rating = int(puzzle.get("rating") or 0)
            if rating < 1700:
                failures.append(f"{puzzle_date}:rating-{rating}")
                continue
            game = chess.pgn.read_game(__import__("io").StringIO(game_data.get("pgn", "")))
            if game is None or game.errors:
                failures.append(f"{puzzle_date}:invalid-source-pgn")
                continue
            all_moves = list(game.mainline_moves())
            initial_ply = int(puzzle.get("initialPly", -1))
            if initial_ply < 0 or initial_ply > len(all_moves):
                failures.append(f"{puzzle_date}:invalid-initial-ply")
                continue
            board = game.board()
            for move in all_moves[:initial_ply]:
                board.push(move)
            start_fen = board.fen()
            solutions = puzzle.get("solution") or []
            if not solutions:
                failures.append(f"{puzzle_date}:empty-solution")
                continue
            sans = []
            for uci in solutions:
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    raise RuntimeError(f"Lichess puzzle {puzzle_id} contains an illegal solution move.")
                sans.append(board.san(move))
                board.push(move)
            pgn = (
                f'[Event "Chess Bits Lichess Puzzle"]\n[Site "Lichess"]\n'
                f'[SetUp "1"]\n[FEN "{start_fen}"]\n[Result "*"]\n\n'
                + " ".join(sans) + " *\n"
            )
            # Re-parse with python-chess before a source position reaches the renderer.
            states, legal_moves, legal_sans, mate = renderer.parse_pgn(pgn, False)
            if len(legal_moves) != len(solutions) or legal_sans != sans:
                raise RuntimeError("Puzzle PGN round-trip did not preserve the complete solution.")
            side = "White" if chess.Board(start_fen).turn == chess.WHITE else "Black"
            themes = [str(theme) for theme in puzzle.get("themes", [])][:5]
            script = (
                f"Welcome to Chess Bits. Here is a tactical puzzle from Lichess, rated {rating}. "
                f"{side} is to move. Pause the video and calculate forcing moves before you look at the solution. "
                "Look for checks, captures, and threats, and make sure every reply has been considered. "
                f"The solution is {', '.join(sans)}. "
                f"The key tactical themes are {', '.join(themes) if themes else 'piece activity and calculation'}. "
                "Notice how the forcing continuation limits the opponent's choices. Do not stop calculating after finding the first good move; check the whole sequence and the final position. "
                + ("The line ends in checkmate." if mate else "The line reaches the puzzle's intended tactical conclusion; compare the final position with the starting position.")
                + " Replay the line once more, then try to find the first move without hints. Save the puzzle and practise calculating all forcing replies. Follow Chess Bits for more chess tactics and opening ideas."
            )
            return pgn, {"id": puzzle_id, "rating": rating, "themes": themes, "mate": mate,
                          "source_date": puzzle_date.isoformat()}, sans, script
        except requests.RequestException as exc:
            failures.append(f"{puzzle_date}:{type(exc).__name__}")
            continue
    raise RuntimeError("No unused Lichess daily puzzle rated 1700+ found in the last 15 days. " + ", ".join(failures[-15:]))


def download_short_music(target: date, out_path: Path) -> tuple[Path, dict]:
    start = target.toordinal() % len(MUSIC)
    failures = []
    for step in range(len(MUSIC)):
        item = MUSIC[(start + step) % len(MUSIC)]
        tmp = out_path.with_suffix(".part")
        try:
            tmp.unlink(missing_ok=True)
            with requests.get(item["url"], stream=True, timeout=(20, 60), allow_redirects=True,
                              headers={"User-Agent": "ChessBitsAutoPublisher/1.0"}) as response:
                response.raise_for_status()
                final = urlparse(response.url)
                if final.scheme != "https":
                    raise RuntimeError("NCS download did not remain on HTTPS.")
                content_type = (response.headers.get("Content-Type") or "").lower()
                with tmp.open("wb") as stream:
                    for chunk in response.iter_content(256 * 1024):
                        if chunk:
                            stream.write(chunk)
                if tmp.stat().st_size < 10_000:
                    raise RuntimeError("NCS returned a file that is too small to be audio.")
                if "text/html" in content_type:
                    raise RuntimeError("NCS download returned an HTML page, not audio.")
                probe_audio(tmp)
                tmp.replace(out_path)
                print(f"SHORT_MUSIC_READY id={item['id']} bytes={out_path.stat().st_size}", flush=True)
                return out_path, item
        except Exception as exc:
            failures.append(f"{item['id']}:{type(exc).__name__}")
            tmp.unlink(missing_ok=True)
    raise RuntimeError("All free NCS tracks failed validation: " + ", ".join(failures))


def render_video(pgn: str, mode: str, title: str, voice_path: Path, out_path: Path,
                 music_path: Path | None, thumbnail_path: Path) -> dict:
    states, moves, sans, mate = renderer.parse_pgn(pgn, False)
    duration = probe_audio(voice_path)
    if mode == "puzzle_short" and duration > 180:
        raise RuntimeError("Puzzle narration is too long for a Short.")
    if mode == "longform" and duration < 90:
        raise RuntimeError("Opening narration is too short; refusing to publish a low-value long-form video.")
    width, height = (1080, 1920) if mode == "puzzle_short" else (1920, 1080)
    total_frames = max(1, math.ceil(duration * renderer.FPS))
    final_hold = max(2.3 if mate else 1.5, duration * (0.12 if mode == "puzzle_short" else 0.23))
    reveal_end = max(0.5, duration - final_hold)
    # Save a clean initial-position frame for the YouTube thumbnail.
    thumb_frame = renderer.frame_at(mode, title, states, moves, sans, mate, 0.0, duration, reveal_end)
    thumb_frame.save(thumbnail_path, format="JPEG", quality=94, optimize=True)
    thumb_frame.close()
    if not thumbnail_path.is_file() or thumbnail_path.stat().st_size < 5_000 or thumbnail_path.stat().st_size > 2_000_000:
        raise RuntimeError("Thumbnail QA failed: missing, too small, or larger than 2 MB.")
    temporary = out_path.with_name("video_part.mp4")
    ffmpeg_log = out_path.with_name("ffmpeg.log")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-filter_threads", "1",
        "-filter_complex_threads", "1", "-y", "-thread_queue_size", "2",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", str(renderer.FPS), "-i", "pipe:0", "-thread_queue_size", "2", "-i", str(voice_path),
    ]
    if music_path:
        cmd += [
            "-stream_loop", "-1", "-thread_queue_size", "2", "-i", str(music_path),
            "-filter_complex", "[1:a]volume=1.0[v];[2:a]volume=0.15[m];[v][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
        ]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += [
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "ultrafast",
        "-tune", "zerolatency", "-threads:v", "1", "-crf", "21",
        "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
        "-c:a", "aac", "-threads:a", "1", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(temporary),
    ]
    print(f"VIDEO_ENCODE_START frames={total_frames} resolution={width}x{height} duration={duration:.2f}s music={bool(music_path)}", flush=True)
    with ffmpeg_log.open("wb") as err_file:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_file)
        try:
            for index in range(total_frames):
                frame = renderer.frame_at(mode, title, states, moves, sans, mate, index / renderer.FPS, duration, reveal_end)
                process.stdin.write(np.asarray(frame, dtype=np.uint8).tobytes())
                del frame
                if index % (renderer.FPS * 5) == 0:
                    print(f"VIDEO_FRAME_PROGRESS frame={index}/{total_frames}", flush=True)
            process.stdin.close()
            code = process.wait(timeout=1800)
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
    if code != 0:
        raise RuntimeError("FFmpeg encode failed: " + ffmpeg_log.read_text(errors="replace")[-1500:])
    temporary.replace(out_path)
    info = json.loads(run_checked(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out_path)], 90))
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise RuntimeError("Output QA failed: video/audio stream missing.")
    if (video.get("width"), video.get("height")) != (width, height):
        raise RuntimeError("Output QA failed: wrong aspect ratio or resolution.")
    output_duration = float(info.get("format", {}).get("duration") or 0)
    if abs(output_duration - duration) > 1.5:
        raise RuntimeError("Output QA failed: narration and video durations do not match.")
    run_checked(["ffmpeg", "-v", "error", "-xerror", "-i", str(out_path), "-f", "null", "-"], min(1800, max(120, int(duration * 3))))
    if out_path.stat().st_size < 500_000:
        raise RuntimeError("Output QA failed: MP4 is unexpectedly small.")
    print(f"VIDEO_QA_PASSED bytes={out_path.stat().st_size} duration={output_duration:.2f}s sha256_ready", flush=True)
    return {
        "duration_seconds": round(output_duration, 2),
        "bytes": out_path.stat().st_size,
        "width": width,
        "height": height,
        "checkmate_confirmed": mate,
        "plies": len(moves),
        "music_included": bool(music_path),
    }


def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_APP_PASSWORD", "").strip()
    recipient = os.getenv("CHESSBITS_NOTIFY_EMAIL", "").strip()
    if not all((host, username, password, recipient)):
        print("EMAIL_SKIPPED: SMTP secrets are not configured.", flush=True)
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = recipient
    message.set_content(body)
    port = int(os.getenv("SMTP_PORT", "465"))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(message)
        print("EMAIL_SENT", flush=True)
    except Exception as exc:
        # Mail failure must not turn a confirmed YouTube upload into a failed publish.
        print(f"EMAIL_FAILED type={type(exc).__name__}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="Validate all curated opening lines without uploading.")
    parser.add_argument("--status-only", action="store_true", help="Print whether a scheduled run is needed.")
    args = parser.parse_args()

    state = load_state()
    target = next_target_date(state)
    if args.status_only:
        print(json.dumps({"needed": target is not None, "target_date": target.isoformat() if target else None}))
        return 0
    if args.self_test:
        renderer.load_pieces()
        validate_openings()
        print(f"SELF_TEST_PASSED openings={len(OPENINGS)} neo_pieces={len(renderer.PIECES)}")
        return 0
    if target is None:
        print("SKIP: today's upload is already recorded; nothing is due.", flush=True)
        return 0

    target_marker = marker_for(target)
    used_puzzles = {row.get("puzzle_id") for row in state.get("published", []) if row.get("puzzle_id")}
    # Authorize before rendering, so a missing/incorrect credential never wastes a full render.
    service, uploads_playlist = youtube_client()
    existing = find_existing_upload(service, uploads_playlist, target_marker)
    if existing and existing["upload_status"] not in ("failed", "rejected", "deleted"):
        item = ensure_public(service, existing["video_id"])
        row = {
            "target_date": target.isoformat(), "kind": next_kind(state), "topic_id": "recovered-upload",
            "title": item.get("snippet", {}).get("title", existing.get("title", "")),
            "video_id": existing["video_id"], "url": f"https://www.youtube.com/watch?v={existing['video_id']}",
            "published_at": datetime.now(TZ).isoformat(), "recovered": True,
        }
        existing_tags = set(existing.get("tags", []))
        row["kind"] = "puzzle" if "ChessBitsPuzzle" in existing_tags else "opening"
        row["topic_id"] = next((tag.split(":", 1)[1] for tag in existing_tags if tag.startswith("ChessBitsTopic:")), "recovered-upload")
        row["puzzle_id"] = next((tag.split(":", 1)[1] for tag in existing_tags if tag.startswith("LichessPuzzle:")), None)
        state.setdefault("published", []).append(row)
        state["published"] = state["published"][-400:]
        save_state(state)
        send_email("Chess Bits upload verified", f"Recovered and verified a public upload for {target.isoformat()}:\n{row['title']}\n{row['url']}")
        print(f"CHESSBITS_PUBLISHED {json.dumps(row)}", flush=True)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    renderer.load_pieces()
    validate_openings()
    kind = next_kind(state)
    music_path = None
    music_meta = None
    puzzle_meta = None
    if kind == "opening":
        # Rotate through curated opening lessons; the PGN is legality-checked before narration or rendering.
        opening_rows = [row for row in OPENINGS if row["id"] not in {x.get("topic_id") for x in state.get("published", [])}]
        entry = opening_rows[0] if opening_rows else OPENINGS[len(state.get("published", [])) % len(OPENINGS)]
        title = entry["title"]
        pgn = pgn_for_opening(entry)
        _, moves, sans, mate = renderer.parse_pgn(pgn, False)
        script = make_opening_script(entry, sans)
        mode = "longform"
        topic_id = entry["id"]
        description = (
            f"{title}\n\nA practical chess opening lesson from Chess Bits. Follow the legal sample line, "
            "learn the strategic ideas, and practise the key decisions. Subscribe for more chess openings, "
            "gambits, tactics, and practical training.\n\n#Chess #ChessOpening #ChessBits"
        )
        tags = ["chess", "chess openings", "chess gambit", "chess strategy", "chess tutorial", "Chess Bits"]
    else:
        pgn, puzzle_meta, solution_sans, script = fetch_puzzle(target, used_puzzles)
        title = f"Can You Find This {('Mate' if puzzle_meta['mate'] else 'Tactical Shot')}? | Chess Puzzle"
        mode = "puzzle_short"
        topic_id = "lichess-" + puzzle_meta["id"]
        description = (
            f"A tactical chess puzzle rated {puzzle_meta['rating']}. Pause before the solution reveal and calculate every reply.\n\n"
            + "Themes: " + ", ".join(puzzle_meta["themes"]) + "\n\n"
        )
        try:
            music_path, music_meta = download_short_music(target, OUT_DIR / "short_music.mp3")
            description += music_meta["credit"] + "\n\n#chess #puzzle #chesstactics"
        except Exception as music_exc:
            # Music is a Shorts-only enhancement, never a reason to miss the daily upload.
            music_path, music_meta = None, None
            description += "#chess #puzzle #chesstactics"
            print(f"SHORT_MUSIC_UNAVAILABLE publishing_without_music type={type(music_exc).__name__}", flush=True)
        tags = ["chess", "chess puzzle", "chess tactics", "mate in 2", "chess shorts", "Chess Bits"]

    voice_path = OUT_DIR / "voiceover.mp3"
    video_path = OUT_DIR / "chess-bits-daily.mp4"
    asyncio.run(create_voiceover(script, voice_path))
    thumbnail_path = OUT_DIR / "start-position.jpg"
    qa = render_video(pgn, mode, title, voice_path, video_path, music_path, thumbnail_path)
    if puzzle_meta:
        tags = tags + ["ChessBitsPuzzle", "LichessPuzzle:" + str(puzzle_meta["id"])]
    else:
        tags = tags + ["ChessBitsOpening", "ChessBitsTopic:" + str(topic_id)]
    video_id, verified, thumbnail_set = publish_video(
        service, uploads_playlist, video_path, title, description, tags, target, mode == "puzzle_short", thumbnail_path
    )
    final_status = verified.get("status", {})
    if final_status.get("privacyStatus") != "public":
        raise RuntimeError("Upload did not pass final public-visibility verification.")
    row = {
        "target_date": target.isoformat(),
        "kind": kind,
        "topic_id": topic_id,
        "title": title,
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "published_at": datetime.now(TZ).isoformat(),
        "qa": qa,
        "puzzle_id": puzzle_meta["id"] if puzzle_meta else None,
        "puzzle_rating": puzzle_meta["rating"] if puzzle_meta else None,
        "music_track": music_meta["id"] if music_meta else None,
        "start_position_thumbnail_set": thumbnail_set,
    }
    state.setdefault("published", []).append(row)
    state["published"] = sorted(state["published"], key=lambda item: item["target_date"])[-400:]
    save_state(state)
    send_email(
        "Chess Bits video published successfully",
        f"Verified public upload for target date {target.isoformat()}.\nTitle: {title}\nType: {kind}\n"
        f"URL: {row['url']}\nDuration: {qa['duration_seconds']} seconds\nMusic included: {qa['music_included']}\n"
        f"Start-position thumbnail set: {thumbnail_set}\n"
        "The uploaded video passed move legality and full audio/video decode checks."
    )
    print(f"CHESSBITS_PUBLISHED {json.dumps(row)}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HttpError as exc:
        print(f"FATAL YouTube API error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
    except Exception as exc:
        print(f"FATAL {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
