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
        "id": "ruy-lopez",
        "title": "Ruy Lopez: Pressure the Centre Before Attacking",
        "opening": "the Ruy Lopez",
        "moves": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Na5 10. Bc2 c5 11. d4 Qc7",
        "hook": "The Ruy Lopez is a model of positional opening play. White develops toward the centre and puts pressure on the defender of e5, while both sides prepare to contest the central pawn structure.",
        "ideas": "The bishop's pressure on the c6-knight influences the e5-pawn, but the strategic point is broader than winning a pawn. White can prepare d4 and build a strong centre; Black can gain queenside space and challenge that centre with ...c5. Each side tries to create a favourable pawn break while keeping the king safe.",
        "plan": "White should complete development, support d4, and avoid allowing Black to resolve the centre on ideal terms. Black should use the queenside space, contest central squares, and finish development before starting a flank attack. The bishop pair is useful only if its diagonals remain active.",
        "mistake": "Do not move the same bishop repeatedly without a concrete reason, and do not assume the pin on the knight is permanent. Black can break the pin or challenge the centre; White must be ready to adapt. Opening plans are flexible ideas, not forced scripts.",
        "exercise": "Before playing d4 or ...c5, count the pieces that support and attack the centre. The side that prepares the break better often obtains the more comfortable middlegame. This is a useful habit in many classical openings.",
    },
    {
        "id": "french-winawer",
        "title": "French Winawer: Space, Structure, and Counterplay",
        "opening": "the French Winawer",
        "moves": "1. e4 e6 2. d4 d5 3. Nc3 Bb4 4. e5 c5 5. a3 Bxc3+ 6. bxc3 Ne7 7. Nf3 Nbc6 8. Bd3 c4 9. Be2 Qa5 10. Bd2 Bd7 11. O-O O-O 12. Ng5 h6",
        "hook": "The French Winawer creates an asymmetric pawn structure early. White gains space with e5, while Black attacks the centre and may damage White's pawns in exchange for dynamic counterplay.",
        "ideas": "The c3-pawn recapture gives White a central pawn duo but leaves a doubled pawn structure. Black's ...c5 challenge is fundamental because it attacks the base of White's centre. White has to use space before Black's counterplay becomes strong, and Black must avoid getting cramped behind the pawn chain.",
        "plan": "White should develop, castle, and consider attacking the kingside only when the centre is secure. Black should keep pressure on d4 and look for piece activity along the dark squares. The side with less space can often improve by exchanging the right pieces, not by making random pawn moves.",
        "mistake": "White should not attack on the kingside while the centre is collapsing. Black should not exchange the light-squared bishop without considering the long-term dark-square consequences. Every pawn break changes which side of the board is easier to play.",
        "exercise": "Identify the base of each pawn chain and the break that attacks it. Then ask whether the pieces are placed behind the pawns that should advance. This helps you form a plan instead of reacting move by move.",
    },
    {
        "id": "alapin-sicilian",
        "title": "Alapin Sicilian: Challenge the Sicilian Before It Settles",
        "opening": "the Alapin Sicilian",
        "moves": "1. e4 c5 2. c3 Nf6 3. e5 Nd5 4. d4 cxd4 5. Nf3 d6 6. cxd4 Nc6 7. Bc4 Nb6 8. Bb3 dxe5 9. Nxe5 Nxe5 10. dxe5 Qxd1+ 11. Kxd1",
        "hook": "The Alapin is a direct response to the Sicilian. White uses c3 to support a central d4 push and aims to build a broad centre without entering the most theoretical open-Sicilian positions.",
        "ideas": "Black's knight pressure on e4 and d5 is important, and White must calculate central exchanges carefully. Once pawns are exchanged, the position can become more open and the value of development rises. A quiet-looking recapture can change the pawn structure and determine which side has targets.",
        "plan": "White should develop rapidly and use central space when it is supported. Black should challenge the centre with timely pawn breaks and use active pieces to make White's central pawns vulnerable. After queens come off, both sides should reassess king activity and minor-piece placement rather than continuing with an automatic attack.",
        "mistake": "White can overextend the centre without enough pieces behind it. Black can allow White to establish space and then struggle to find a break. Before trading pawns, check which file opens and whether the resulting endgame favours your pieces.",
        "exercise": "Replay the early central exchanges and note how the d-pawn changes roles. Then list the best square for each knight. The exercise is to find a move that improves a piece while also challenging the centre.",
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
        "id": "queens-gambit-declined",
        "title": "Queen's Gambit Declined: Build Pressure on the Centre",
        "opening": "the Queen's Gambit Declined",
        "moves": "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 8. cxd5 Nxd5 9. Bxe7 Qxe7 10. Nxd5 exd5 11. Rc1 Be6 12. Qa4",
        "hook": "The Queen's Gambit Declined is a lesson in central tension. White challenges the d5-pawn with c4, while Black supports it with e6 and aims for a sturdy structure.",
        "ideas": "Neither side needs to resolve the centre immediately. White can add pressure and develop pieces before deciding whether to exchange on d5; Black can maintain the pawn chain or seek a freeing break. The bishop pair and piece activity become important once the centre opens.",
        "plan": "White should complete development, place a rook on the c-file, and use the queen to increase pressure only when it cannot be chased with tempo. Black should seek ...c5 or ...e5 at the right moment and avoid remaining cramped. The central pawn structure determines the best squares for the minor pieces.",
        "mistake": "A common mistake is to trade in the centre without understanding which piece will recapture and which file will open. Another is to keep tension forever and allow the opponent to improve freely. Make each pawn exchange part of a plan.",
        "exercise": "Before exchanging on d5, identify both recaptures and the resulting pawn structure. Then choose a developing move that keeps the option open. Good opening play often means preserving useful choices until the position tells you which one is best.",
    },
    {
        "id": "italian-game",
        "title": "Italian Game: Development First, Attack Second",
        "opening": "the Italian Game",
        "moves": "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 6. cxd4 Bb4+ 7. Nc3 Nxe4 8. O-O Bxc3 9. d5 Bf6 10. Re1 Ne7 11. Rxe4 d6 12. Bg5 Bxg5 13. Nxg5 O-O",
        "hook": "The Italian Game provides a natural route to the centre, but the key decisions are not simply about attacking f7. White and Black both look for a safe king, active pieces, and a favourable central break.",
        "ideas": "White's c3 and d4 challenge the centre directly, while Black must decide whether to exchange central pawns or keep the tension. The bishop on c4 creates pressure but can become a target if White loses tempi. Once the centre opens, tactical details around e4 and the e-file become important.",
        "plan": "White should develop, castle, and use the e-file when exchanges create a target. Black should contest the centre, complete development, and avoid unnecessary king-side weaknesses. The best attack grows out of a central advantage and well-coordinated pieces.",
        "mistake": "Do not attack f7 automatically just because the bishop points there. If Black can defend while developing, the attacker may lose time. Also check every central capture before castling, because tactical exchanges can change whether the king is safe.",
        "exercise": "At each central exchange, write down which piece will recapture and where it will stand afterward. Then ask whether the exchange improves development or creates a target. This makes the Italian Game a practical lesson in timing and coordination.",
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
                }
    return None


def ensure_public(service, video_id: str) -> dict:
    last = {}
    for attempt in range(18):
        response = service.videos().list(part="snippet,status", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"YouTube did not return uploaded video {video_id}.")
        item = items[0]
        status = item.get("status", {})
        last = status
        if status.get("uploadStatus") in ("failed", "rejected", "deleted"):
            raise RuntimeError(f"YouTube rejected or failed video {video_id}: {status}")
        if status.get("privacyStatus") != "public":
            try:
                service.videos().update(
                    part="status",
                    body={"id": video_id, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}},
                ).execute()
            except HttpError as exc:
                raise RuntimeError(
                    "YouTube accepted the upload but would not make it public. Check whether the YouTube API "
                    "project has completed Google's required upload audit. The video was not deleted."
                ) from exc
        time.sleep(10)
        response = service.videos().list(part="snippet,status", id=video_id).execute()
        item = (response.get("items") or [{}])[0]
        status = item.get("status", {})
        if status.get("privacyStatus") == "public" and status.get("uploadStatus") not in ("failed", "rejected", "deleted"):
            return item
    if last.get("privacyStatus") != "public":
        raise RuntimeError(
            "Upload is present but is not public; automated publishing is blocked, possibly by the YouTube API project audit."
        )
    return {"id": video_id, "status": last, "snippet": {}}


def publish_video(service, uploads_playlist: str, video_path: Path, title: str, description: str,
                  tags: list[str], target: date, short: bool) -> tuple[str, dict]:
    marker = marker_for(target)
    existing = find_existing_upload(service, uploads_playlist, marker)
    if existing:
        if existing["upload_status"] in ("failed", "rejected", "deleted"):
            raise RuntimeError(
                f"A previous upload for {target.isoformat()} exists but YouTube marked it {existing['upload_status']}; "
                "stopping to avoid duplicate public videos."
            )
        item = ensure_public(service, existing["video_id"])
        return existing["video_id"], item

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
            verified = ensure_public(service, video_id)
            return video_id, verified
        except Exception as exc:
            last_error = exc
            # Before a new attempt, detect whether YouTube accepted the upload before the connection failed.
            try:
                existing = find_existing_upload(service, uploads_playlist, marker)
                if existing and existing["upload_status"] not in ("failed", "rejected", "deleted"):
                    item = ensure_public(service, existing["video_id"])
                    return existing["video_id"], item
            except Exception:
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
    url = "https://lichess.org/api/puzzle/daily?date=" + target.strftime("%Y%m%d")
    response = requests.get(url, timeout=(15, 45), headers={"User-Agent": "ChessBitsAutoPublisher/1.0 contact: chess-bits"})
    response.raise_for_status()
    data = response.json()
    puzzle = data.get("puzzle", {})
    game_data = data.get("game", {})
    puzzle_id = str(puzzle.get("id", ""))
    if not puzzle_id or puzzle_id in used_ids:
        raise RuntimeError(f"Lichess daily puzzle is missing or already used: {puzzle_id or 'no id'}")
    rating = int(puzzle.get("rating") or 0)
    if rating < 1700:
        raise RuntimeError(f"Lichess puzzle rating {rating} is below the 1700 difficulty floor.")
    game = chess.pgn.read_game(__import__("io").StringIO(game_data.get("pgn", "")))
    if game is None or game.errors:
        raise RuntimeError("Lichess puzzle supplied an invalid source PGN.")
    all_moves = list(game.mainline_moves())
    initial_ply = int(puzzle.get("initialPly", -1))
    if initial_ply < 0 or initial_ply > len(all_moves):
        raise RuntimeError("Lichess puzzle has an invalid starting ply.")
    board = game.board()
    for move in all_moves[:initial_ply]:
        board.push(move)
    start_fen = board.fen()
    solutions = puzzle.get("solution") or []
    if not solutions:
        raise RuntimeError("Lichess puzzle has no solution.")
    sans = []
    for uci in solutions:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise RuntimeError("Lichess puzzle solution failed legality validation.")
        sans.append(board.san(move))
        board.push(move)
    solution_text = " ".join(f"{i + 1}. {san}" for i, san in enumerate(sans))
    pgn = (
        f'[Event "Chess Bits Lichess Puzzle"]\n[Site "Lichess"]\n'
        f'[SetUp "1"]\n[FEN "{start_fen}"]\n[Result "*"]\n\n'
        + " ".join(f"{san}" for san in sans) + " *\n"
    )
    # Re-parse the produced PGN independently so a malformed FEN header cannot reach rendering.
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
    meta = {"id": puzzle_id, "rating": rating, "themes": themes, "mate": mate}
    return pgn, meta, sans, script


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
                 music_path: Path | None) -> dict:
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
        music_path, music_meta = download_short_music(target, OUT_DIR / "short_music.mp3")
        description += music_meta["credit"] + "\n\n#chess #puzzle #chesstactics"
        tags = ["chess", "chess puzzle", "chess tactics", "mate in 2", "chess shorts", "Chess Bits"]

    voice_path = OUT_DIR / "voiceover.mp3"
    video_path = OUT_DIR / "chess-bits-daily.mp4"
    asyncio.run(create_voiceover(script, voice_path))
    qa = render_video(pgn, mode, title, voice_path, video_path, music_path)
    video_id, verified = publish_video(
        service, uploads_playlist, video_path, title, description, tags, target, mode == "puzzle_short"
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
    }
    state.setdefault("published", []).append(row)
    state["published"] = sorted(state["published"], key=lambda item: item["target_date"])[-400:]
    save_state(state)
    send_email(
        "Chess Bits video published successfully",
        f"Verified public upload for target date {target.isoformat()}.\nTitle: {title}\nType: {kind}\n"
        f"URL: {row['url']}\nDuration: {qa['duration_seconds']} seconds\nMusic included: {qa['music_included']}\n"
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
