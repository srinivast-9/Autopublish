#!/usr/bin/env python3
"""Free, self-healing daily Chess Bits publisher.

Uses the repository's approved Neo renderer, free Edge TTS, a mixed pool of
curated classic tactical positions and high-difficulty public puzzle data, free
credited music for Shorts only, and the official YouTube Data API. Long-form
voiceovers intentionally have no background music.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
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
    {
        "id": "evergreen-sacrifice-battery",
        "focus": "the knight check that deflects the g-pawn, the rook offer on e7, and the queen offer that draws the king into the bishops' mating net",
        "takeaway": "Each sacrifice has a concrete job: Nf6+ draws the g-pawn away, Rxe7+ pulls a defender to e7, and Qxd7+ lures the king into the bishops' mating net. Calculate the forcing replies that make each offer work.",
        "training_prompt": "Pause before Nf6+ and Qxd7+. For each sacrifice, identify the defender being diverted and explain why the bishop that remained on a3 becomes decisive.",
        "move_notes": {"16":"The pawn advances to e5 with tempo against Black's queen on f6. Attacking the queen while gaining central space forces it to move and gives White more time to bring the remaining pieces into the attack.","32":"The knight sacrifice on f6 is a deflection idea: the check invites Black's g-pawn to capture. If Black accepts, the kingside pawn cover is damaged and White's e-pawn can recapture to create a dangerous passed pawn.","34":"The e-pawn recaptures on f6, removing the deflecting pawn and becoming a dangerous advanced passer. Black must now spend time controlling that pawn while White's pieces continue attacking.","38":"The rook sacrifice on e7 is a forcing deflection. If Black's knight captures the rook, the d7 pawn and king become vulnerable to the queen's next check; the point is the sequence, not the rook by itself.","40":"White deliberately offers the queen on d7 with check. If the king accepts, it is drawn away from the back rank and into the bishops' mating net. This queen sacrifice works only because the following checks are forcing.","46":"The bishop captures the knight on e7 and delivers mate. The bishop that stayed on a3 joins at exactly the right moment, while the other attacking pieces have driven the king onto vulnerable squares."},
        "lesson_type": "tactics",
        "title": "The Evergreen Combination: Sacrifice, Deflection, and a Mating Battery",
        "opening": "queen sacrifice, deflection, and mating batteries",
        "moves": "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4 exd4 7. O-O d3 8. Qb3 Qf6 9. e5 Qg6 10. Re1 Nge7 11. Ba3 b5 12. Qxb5 Rb8 13. Qa4 Bb6 14. Nbd2 Bb7 15. Ne4 Qf5 16. Bxd3 Qh5 17. Nf6+ gxf6 18. exf6 Rg8 19. Rad1 Qxf3 20. Rxe7+ Nxe7 21. Qxd7+ Kxd7 22. Bf5+ Ke8 23. Bd7+ Kf8 24. Bxe7#",
        "hook": "This lesson follows a famous attacking combination in which material is repeatedly offered to keep the initiative. The point is not to memorize a spectacular game: notice how checks, captures, and direct threats keep the defender from reorganizing. A sacrifice is justified only when the follow-up is concrete.",
        "ideas": "The combination combines deflection with a sequence of forcing moves and a final mating battery. When the king is exposed, a defender can be overloaded: a piece may be required to stop mate, protect the queen, and guard a back-rank square at once. The attacker uses tempo to make these duties impossible to satisfy together. Always verify the opponent's best reply before calling a sacrifice sound.",
        "plan": "During a forcing attack, calculate checks first, then captures, then direct threats. After every forcing move, ask what the defender is compelled to do and which defensive task has been abandoned. When the king is driven toward the back rank, look for a rook or bishop that can join the attack with tempo.",
        "mistake": "Do not imitate the sacrifices without checking whether the same forcing replies exist. If the opponent can trade queens, block the checking line, or return material to consolidate, the attack may fail. The final mating pattern works because the pieces cooperate and the defender's replies remain constrained.",
        "exercise": "Pause before the first forcing check and write down every legal king response. Continue the line one move at a time; after each reply, name the threat that remains. Then go back two moves and see whether the defender could have declined the sacrifice or exchanged an attacker. Further study: Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition).",
        "book_reference": "Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition)"
    },
    {
        "id": "opera-deflection-rook-battery",
        "focus": "how the knight offer draws a pawn away, how the rooks seize the open d-file, and how the final queen sacrifice clears the mating line",
        "takeaway": "The early knight offer draws Black's c-pawn away so the bishop can recapture with check. At the finish, Qb8+ lures the knight away from d7 and allows Rd8 mate along the open file.",
        "training_prompt": "At Nxb5, identify which pawn is being lured off its file. At Qb8+, find why the knight's capture of the queen leaves the rook's mating route open.",
        "move_notes": {"18":"White's knight takes the pawn on b5, allowing Black's c-pawn to recapture. That is the point of the offer: draw the c-pawn away so the bishop can recapture on b5 with check.","20":"The bishop recaptures on b5 with check. The knight offer has removed both the b-pawn and the c-pawn, and the check gains a tempo by forcing Black to block with the other knight.","24":"The rook sacrifice on d7 clears the file and pulls Black's rook from d8 down to d7. White's remaining rook can then take over the open d-file; the point is the coordination sequence, not a one-move exchange win.","30":"The queen check on b8 is a deliberate sacrifice. Black's knight can capture it, but that pulls the defender away from d7 and allows White's rook to reach d8 with mate.","32":"The rook slides to d8 for checkmate because the queen bait has removed Black's knight from d7 and the d-file is open. The king has no legal escape."},
        "lesson_type": "tactics",
        "title": "Deflection and the Rook Battery: A Complete Tactical Combination",
        "opening": "deflection, sacrifice, and a final rook battery",
        "moves": "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8#",
        "hook": "A successful combination often depends on one defender being pulled away at exactly the right moment. In this classic attacking line, material is given up to open lines and lure pieces away from the squares that matter. Follow the forcing moves rather than judging each exchange in isolation.",
        "ideas": "The main themes are deflection, removal of defenders, and a rook battery on the open file. A sacrifice is not automatically sound because it looks dramatic: calculate the legal replies and identify which defensive task becomes impossible. The final move works because the pieces coordinate along the back rank and the king has no safe escape.",
        "plan": "When calculating a forcing line, first list checks and captures. For each possible reply, ask whether it blocks a line, removes a checking piece, or protects the mating square. Look for a defender that is overloaded or can be decoyed away, then confirm that the follow-up remains forcing.",
        "mistake": "The common error is to stop calculating after the first sacrifice. The defender may have an interposition or countercheck, and a rook battery only works when the line is open and the back rank is controlled. Verify the exact position after every recapture instead of relying on a familiar pattern.",
        "exercise": "Pause before the first sacrifice and count the defenders around the king. Then follow the sequence until mate, checking every legal response. For further study, consult Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition), and compare how deflection differs from a pin.",
        "book_reference": "Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition)"
    },
    {
        "id": "immortal-game-sacrifice",
        "focus": "how the opening exposes White's king, how the e-pawn gains tempo against the knight, and how the queen sacrifice deflects the final defender",
        "takeaway": "The finishing idea is more than a queen sacrifice: Qf6+ induces the knight on g8 to capture the queen, drawing it away from e7. That lets the bishop deliver mate on e7.",
        "training_prompt": "Before Qf6+, identify the defenders around Black's king. After ...Nxf6, explain why Be7 is mate and which defensive square the knight has abandoned.",
        "move_notes": {"4":"The bishop develops to c4 and targets f7, one of Black's most vulnerable squares before castling. White is building a concrete target, but the king on f1 will soon need care.","5":"Black's queen check on h4 exploits White's exposed king before it can castle. The check forces a king move and shows why attacking chances must always be weighed against king safety.","36":"The e-pawn advances to e5 and attacks the knight on f6 with tempo. This central thrust gains space while forcing Black to address a new threat instead of simply consolidating the extra material.","40":"The knight captures the g7 pawn with check, forcing the king toward d8 and keeping the attack alive. The check is useful because it brings the king toward the squares the remaining pieces can target.","42":"Qf6+ is a deliberate queen sacrifice. Black's knight can take the queen, but doing so moves it from g8 and abandons control of e7, allowing the bishop to finish with mate."},
        "lesson_type": "tactics",
        "title": "A Storm of Sacrifices: Initiative, Deflection, and Checkmate",
        "opening": "forcing sacrifices and a mating attack",
        "moves": "1. e4 e5 2. f4 exf4 3. Bc4 Qh4+ 4. Kf1 b5 5. Bxb5 Nf6 6. Nf3 Qh6 7. d3 Nh5 8. Nh4 Qg5 9. Nf5 c6 10. g4 Nf6 11. Rg1 cxb5 12. h4 Qg6 13. h5 Qg5 14. Qf3 Ng8 15. Bxf4 Qf6 16. Nc3 Bc5 17. Nd5 Qxb2 18. Bd6 Bxg1 19. e5 Qxa1+ 20. Ke2 Na6 21. Nxg7+ Kd8 22. Qf6+ Nxf6 23. Be7#",
        "hook": "This tactical lesson is about initiative: several pieces are offered, but every sacrifice has to gain time or open a decisive line. The aim is to recognize when an exposed king and undeveloped pieces make forcing play more important than material count.",
        "ideas": "Watch for deflection, discovered threats, and the way checks restrict the king's choices. The attacking side keeps changing the problem the defender must solve; while the queen and rooks appear to be lost, the remaining pieces build a mating net. This is a historical illustration, not a rule that sacrifices are generally correct.",
        "plan": "In sharp positions, calculate forcing moves before quiet moves. Trace every checking line and identify which defensive piece is being removed or distracted. If a sacrifice opens a file or diagonal, verify that another piece can use that line immediately and that the king cannot escape.",
        "mistake": "A spectacular attack should not be copied without calculation. If the defender can close the line, exchange queens, or escape the checking net, the same material investment may be unsound. The test is the concrete position after the opponent's best defence.",
        "exercise": "At each check, pause and list all legal replies. Then track which squares become unavailable and which attacking piece can join next. For further study, Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition) offers a classic framework for studying forcing combinations.",
        "book_reference": "Technique of Modern Tactics by P. S. Bond and M. J. McDonough (1919, public-domain edition)"
    }
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
    # Assign content type by calendar day, not by the last individual upload.
    # A same-day extra Short or recovery must not shift tomorrow's alternation.
    latest_date = max(date.fromisoformat(row["target_date"]) for row in rows)
    primary = next(row for row in rows if date.fromisoformat(row["target_date"]) == latest_date)
    return "puzzle" if primary["kind"] == "opening" else "opening"


def marker_for(target: date, kind: str | None = None) -> str:
    marker = "CB" + target.strftime("%Y%m%d")
    # Only forced same-day extras need a kind-specific marker. Keep the legacy
    # date marker for scheduled runs so any accepted upload can still be recovered.
    if kind == "puzzle":
        return marker + "P"
    return marker


def pgn_for_opening(entry: dict) -> str:
    lesson_type = entry.get("lesson_type", "opening")
    event = "Chess Bits Tactical Lesson" if lesson_type == "tactics" else "Chess Bits Opening Lesson"
    black = "Tactical demonstration" if lesson_type == "tactics" else entry["opening"]
    return (
        f'[Event "{event}"]\n'
        f'[Site "Chess Bits"]\n[White "Chess Bits"]\n[Black "{black}"]\n'
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
        # Also verify that each move's SAN can be spoken without misreading + or #.
        for index, move in enumerate(moves):
            for note_ply, note in entry.get("move_notes", {}).items():
                if not str(note_ply).isdigit() or int(note_ply) < 0 or int(note_ply) >= len(moves) or not str(note).strip():
                    raise RuntimeError(f"Invalid move commentary index or empty note in {entry['id']}: {note_ply}")
            move_narration(states[index], move, sans[index], entry, index)


def validate_synchronized_animation() -> None:
    """Smoke-test narration cue construction and both render layouts without uploading."""
    entry = OPENINGS[0]
    states, moves, sans, mate = renderer.parse_pgn(pgn_for_opening(entry), False)
    segments = make_opening_segments(entry, states, moves, sans)
    if len(segments) != len(moves) + 2 or any(not segment.strip() for segment in segments):
        raise RuntimeError("Opening narration must include a non-empty intro, one clip per move, and an outro.")
    if len([move_narration(states[i], move, sans[i], entry, i) for i, move in enumerate(moves)]) != len(moves):
        raise RuntimeError("There must be exactly one spoken move cue for every legal move.")
    tactical_entry = next((item for item in OPENINGS if item.get("lesson_type") == "tactics" and item.get("move_notes")), None)
    if tactical_entry is not None:
        tactical_states, tactical_moves, tactical_sans, _ = renderer.parse_pgn(pgn_for_opening(tactical_entry), False)
        tactical_segments = make_opening_segments(tactical_entry, tactical_states, tactical_moves, tactical_sans)
        for note_ply, note in tactical_entry.get("move_notes", {}).items():
            if str(note) not in tactical_segments[int(note_ply) + 1]:
                raise RuntimeError(f"Position-specific commentary was not attached to ply {note_ply} of {tactical_entry['id']}.")
        generic_phrases = ("The knight's new square changes", "The rook is improving its line", "Check whether the capturing piece can be recaptured")
        if any(phrase in segment for segment in tactical_segments for phrase in generic_phrases):
            raise RuntimeError("Generic repetitive move narration has reappeared.")
    windows = [(0.5 + i * 1.5, 1.2 + i * 1.5) for i in range(len(moves))]
    duration = windows[-1][1] + 2.0
    long_frame = renderer.frame_at(
        "longform", entry["title"], states, moves, sans, mate, 0.8, duration, duration - 1.0, windows
    )
    if long_frame.size != (1920, 1080):
        raise RuntimeError("Long-form synchronized render has the wrong dimensions.")
    long_frame.close()
    short_frame = renderer.frame_at(
        "puzzle_short", "Sync test", states, moves, sans, mate, 0.8, duration, duration - 1.0, windows
    )
    if short_frame.size != (1080, 1920):
        raise RuntimeError("Short-form synchronized render has the wrong dimensions.")
    short_frame.close()


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
                  tags: list[str], target: date, short: bool, thumbnail_path: Path | None = None,
                  marker: str | None = None) -> tuple[str, dict, bool]:
    marker = marker or marker_for(target)
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


def speak_square(square: chess.Square) -> str:
    """Spell a chess square in TTS-friendly language."""
    return f"{chess.FILE_NAMES[chess.square_file(square)]} {chess.square_rank(square) + 1}"


def spoken_san(board: chess.Board, move: chess.Move, san: str) -> str:
    """Render SAN as natural speech: '+' is 'check', '#' is 'checkmate', never 'plus' or 'hash'."""
    core = san.rstrip("!?")
    after = board.copy(stack=False)
    after.push(move)
    is_mate = after.is_checkmate()
    is_check = after.is_check()
    if san.endswith("#") != is_mate:
        raise RuntimeError(f"SAN checkmate marker disagrees with resulting board: {san}")
    if san.endswith("+") and not is_check:
        raise RuntimeError(f"SAN check marker disagrees with resulting board: {san}")

    if board.is_castling(move):
        phrase = "castle kingside" if chess.square_file(move.to_square) == 6 else "castle queenside"
    else:
        clean = core.rstrip("+#")
        match = re.match(r"^(?P<piece>[KQRBN]?)(?P<prefix>[a-h1-8]{0,2})(?P<capture>x?)(?P<dest>[a-h][1-8])(?P<promotion>=[QRBN])?$", clean)
        if not match:
            raise RuntimeError(f"Could not convert SAN to speech safely: {san}")
        piece_code = match.group("piece")
        piece_names = {"": "pawn", "K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
        piece_name = piece_names[piece_code]
        prefix = match.group("prefix")
        takes = bool(match.group("capture"))
        destination = match.group("dest")
        target = f"{destination[0]} {destination[1]}"
        if len(prefix) == 2 and prefix[0] in chess.FILE_NAMES and prefix[1] in "12345678":
            origin_phrase = f"from {prefix[0]} {prefix[1]}"
        elif prefix and prefix[0] in chess.FILE_NAMES:
            origin_phrase = f"from file {prefix[0]}"
        elif prefix:
            origin_phrase = f"from rank {prefix}"
        else:
            origin_phrase = ""
        if takes:
            phrase = f"{piece_name} {origin_phrase + ' ' if origin_phrase else ''}takes {target}"
        else:
            phrase = f"{piece_name} {origin_phrase + ' ' if origin_phrase else ''}to {target}"
        promotion = match.group("promotion")
        if promotion:
            promo_names = {"Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
            phrase += f", promoting to a {promo_names[promotion[1]]}"
        if board.is_en_passant(move):
            phrase += " en passant"

    # Derive the spoken check annotation from the actual resulting position, not punctuation alone.
    if is_mate:
        phrase += ", checkmate"
    elif is_check:
        phrase += ", check"
    return phrase


def _piece_word(piece: chess.Piece | None) -> str:
    if piece is None:
        return "piece"
    return {
        chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
        chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
    }[piece.piece_type]


def _square_voice(square: chess.Square) -> str:
    """Format a square in a way that TTS reliably reads aloud."""
    return f"{chess.FILE_NAMES[chess.square_file(square)]} {chess.square_rank(square) + 1}"


def move_narration(board: chess.Board, move: chess.Move, san: str,
                   entry: dict | None = None, ply: int | None = None) -> str:
    """Narrate the legal move and add concrete analysis only when the position supports it."""
    side = "White" if board.turn == chess.WHITE else "Black"
    opponent = not board.turn
    opponent_name = "White" if opponent == chess.WHITE else "Black"
    piece = board.piece_at(move.from_square)
    if piece is None:
        raise RuntimeError("Cannot narrate a move without a moving piece.")
    piece_name = _piece_word(piece)
    move_callout = spoken_san(board, move, san)
    after = board.copy(stack=False)
    after.push(move)

    # Hand-written annotations are indexed by zero-based ply and take priority over
    # generic analysis. This is where the lesson explains the actual idea behind a key move.
    if entry is not None and ply is not None:
        note = entry.get("move_notes", {}).get(str(ply))
        if note:
            return f"{side} plays {move_callout}. {note}"

    if after.is_checkmate():
        return f"{side} plays {move_callout}. The king has no legal escape; the mating net is complete."

    if after.is_check():
        king_square = after.king(opponent)
        checking_squares = after.attackers(board.turn, king_square) if king_square is not None else set()
        if move.to_square not in checking_squares:
            discovered_from = next(
                (sq for sq in checking_squares if sq != move.to_square and after.piece_at(sq) is not None),
                None,
            )
            if discovered_from is not None:
                discovered_piece = _piece_word(after.piece_at(discovered_from))
                return (
                    f"{side} plays {move_callout}. By vacating {_square_voice(move.from_square)}, "
                    f"the move uncovers check from the {discovered_piece} on {_square_voice(discovered_from)}."
                )
        return (
            f"{side} plays {move_callout}. The {piece_name} gives check directly, "
            "so the defender must answer before continuing its own plan."
        )

    # Detect a newly created fork against major pieces by the piece that just moved.
    major_targets = []
    for target_square, target_piece in after.piece_map().items():
        if target_piece.color != opponent or target_piece.piece_type not in (chess.QUEEN, chess.ROOK):
            continue
        if move.to_square in after.attackers(board.turn, target_square) and \
                move.from_square not in board.attackers(board.turn, target_square):
            major_targets.append((target_square, target_piece))
    if len(major_targets) >= 2:
        target_text = " and ".join(
            f"{opponent_name}'s {_piece_word(target_piece)} on {_square_voice(square)}"
            for square, target_piece in major_targets[:2]
        )
        return (
            f"{side} plays {move_callout}. This creates a fork against {target_text}; "
            "the defender has two major threats to deal with at once."
        )
    if len(major_targets) == 1:
        target_square, target_piece = major_targets[0]
        return (
            f"{side} plays {move_callout}. The {piece_name} now attacks "
            f"{opponent_name}'s {_piece_word(target_piece)} on {_square_voice(target_square)}, "
            "so it must be moved or defended."
        )

    # Detect a newly opened sliding attack, such as a rook or bishop line revealed
    # when another piece moves out of the way.
    for target_square, target_piece in after.piece_map().items():
        if target_piece.color != opponent or target_piece.piece_type not in (
            chess.QUEEN, chess.ROOK, chess.BISHOP
        ):
            continue
        old_attackers = board.attackers(board.turn, target_square)
        for source_square in after.attackers(board.turn, target_square):
            if source_square == move.to_square or source_square in old_attackers:
                continue
            source_piece = after.piece_at(source_square)
            if source_piece is not None and source_piece.piece_type in (
                chess.ROOK, chess.BISHOP, chess.QUEEN
            ):
                return (
                    f"{side} plays {move_callout}. Moving the {piece_name} away from "
                    f"{_square_voice(move.from_square)} opens the { _piece_word(source_piece) } "
                    f"on {_square_voice(source_square)} against {opponent_name}'s "
                    f"{_piece_word(target_piece)} on {_square_voice(target_square)}."
                )

    # A newly pinned enemy piece cannot move freely without exposing its king.
    for target_square, target_piece in after.piece_map().items():
        if target_piece.color == opponent and target_piece.piece_type != chess.KING:
            if after.is_pinned(opponent, target_square) and not board.is_pinned(opponent, target_square):
                return (
                    f"{side} plays {move_callout}. This pins {opponent_name}'s "
                    f"{_piece_word(target_piece)} on {_square_voice(target_square)} to its king; "
                    "moving it would expose check."
                )

    if board.is_castling(move):
        return (
            f"{side} plays {move_callout}. Castling secures the king and brings a rook toward "
            "the centre, where open files may become important."
        )

    if board.is_en_passant(move):
        return (
            f"{side} plays {move_callout}. En passant removes the pawn from the square it passed, "
            "so the capture changes the pawn structure in a way an ordinary capture does not."
        )

    if move.promotion:
        return (
            f"{side} plays {move_callout}. The pawn promotes on {_square_voice(move.to_square)}; "
            "the new piece must still be checked for immediate tactical threats."
        )

    # Explain central pawn moves with the actual squares they now control.
    if piece.piece_type == chess.PAWN:
        destination_file = chess.square_file(move.to_square)
        destination_rank = chess.square_rank(move.to_square)
        if destination_file in (3, 4) and destination_rank in (2, 3, 4, 5):
            centre = (chess.D4, chess.E4, chess.D5, chess.E5)
            controlled = [
                chess.square_name(square) for square in centre
                if square in after.attacks(move.to_square)
            ]
            if controlled:
                targets = " and ".join(f"{sq[0]} {sq[1]}" for sq in controlled)
                return (
                    f"{side} plays {move_callout}. The central pawn now attacks {targets}, "
                    "helping contest the centre and opening lines for the pieces behind it."
                )

    # Explain genuine piece development using the central squares controlled from its new square.
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        home_rank = 0 if board.turn == chess.WHITE else 7
        if chess.square_rank(move.from_square) == home_rank:
            centre = (chess.D4, chess.E4, chess.D5, chess.E5)
            controlled = [
                chess.square_name(square) for square in centre
                if square in after.attacks(move.to_square)
            ]
            if controlled:
                targets = " and ".join(f"{sq[0]} {sq[1]}" for sq in controlled)
                return (
                    f"{side} plays {move_callout}. The {piece_name} develops to "
                    f"{_square_voice(move.to_square)} and adds control over {targets}."
                )

    # Quiet moves need not be padded with generic advice after every single ply.
    # Their SAN callout remains synchronized with the board animation.
    return f"{side} plays {move_callout}"


def make_opening_segments(entry: dict, states: list[chess.Board],
                          moves: list[chess.Move], sans: list[str]) -> list[str]:
    is_tactics = entry.get("lesson_type") == "tactics"
    if is_tactics:
        focus = entry.get("focus", entry["opening"])
        intro = (
            f"Welcome back to Chess Bits. Today's lesson is {entry['title']}. "
            f"{entry['hook']} Watch for {focus}."
        )
    else:
        intro = (
            f"Welcome back to Chess Bits. Today we are studying {entry['opening']}. "
            f"{entry['hook']}"
        )

    move_segments = [
        move_narration(states[i], move, sans[i], entry, i)
        for i, move in enumerate(moves)
    ]

    if is_tactics:
        takeaway = entry.get("takeaway", entry["plan"])
        training_prompt = entry.get("training_prompt", entry["exercise"])
        outro = f"Key takeaway: {takeaway} Training question: {training_prompt}"
        book_reference = entry.get("book_reference")
        if book_reference:
            outro += f" For further study, see {book_reference}."
    else:
        outro = (
            f"Practical plan: {entry['plan']} "
            f"One mistake to avoid: {entry['mistake']} "
            f"Training exercise: {entry['exercise']} "
            "Thanks for watching Chess Bits."
        )
    return [intro, *move_segments, outro]

def create_segmented_voiceover(segments: list[str | None], voice_path: Path,
                               segment_dir_name: str, move_start_segment: int,
                               move_count: int) -> list[tuple[float, float]]:
    """Synthesize narration clips, concatenate them losslessly, and return one animation window per move.

    A None segment inserts seven seconds of silence, used as the puzzle think timer.
    Move tweens are about 0.7 seconds long; the resulting board position holds while
    that move's explanation finishes.
    """
    segment_dir = OUT_DIR / segment_dir_name
    segment_dir.mkdir(parents=True, exist_ok=True)
    wav_paths: list[Path] = []
    durations: list[float] = []

    for index, text in enumerate(segments):
        wav_path = segment_dir / f"segment_{index:03d}.wav"
        if text is None:
            run_checked([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t", "7.0", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav_path),
            ], 90)
        else:
            mp3_path = segment_dir / f"segment_{index:03d}.mp3"
            asyncio.run(create_voiceover(text.strip(), mp3_path))
            run_checked([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3_path),
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav_path),
            ], 180)
        durations.append(probe_audio(wav_path))
        wav_paths.append(wav_path)

    if move_start_segment < 1 or move_start_segment + move_count > len(segments) - 1:
        raise RuntimeError("Narration segment indices do not leave an intro and outro around every move.")
    concat_list = segment_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in wav_paths) + "\n",
        encoding="utf-8",
    )
    run_checked([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(voice_path),
    ], 600)
    combined_duration = probe_audio(voice_path)
    if abs(combined_duration - sum(durations)) > 0.35:
        raise RuntimeError(
            f"Segmented voiceover timing mismatch: segments={sum(durations):.3f}s, combined={combined_duration:.3f}s"
        )

    move_windows: list[tuple[float, float]] = []
    cursor = sum(durations[:move_start_segment])
    for offset in range(move_count):
        move_duration = durations[move_start_segment + offset]
        # Begin almost immediately after the spoken move starts, animate quickly,
        # then hold the new position while the move's explanation continues.
        start = cursor + min(0.22, move_duration * 0.08)
        animation = min(0.72, max(0.45, move_duration * 0.24))
        animation = min(animation, max(0.35, move_duration - 0.25))
        end = min(cursor + move_duration - 0.05, start + animation)
        if end <= start:
            raise RuntimeError(f"Invalid animation window for move {offset + 1}.")
        move_windows.append((round(start, 4), round(end, 4)))
        cursor += move_duration

    if len(move_windows) != move_count:
        raise RuntimeError("Narration timeline does not contain exactly one window per legal move.")
    if any(move_windows[i][1] > move_windows[i + 1][0] for i in range(len(move_windows) - 1)):
        raise RuntimeError("Narration move windows overlap.")
    if move_windows and move_windows[-1][1] >= combined_duration:
        raise RuntimeError("Last move animation extends past the finished voiceover.")
    print(
        f"MOVE_TIMELINE_READY type={segment_dir_name} moves={len(move_windows)} duration={combined_duration:.2f}s "
        f"average_animation={sum(end-start for start, end in move_windows)/len(move_windows):.2f}s",
        flush=True,
    )
    return move_windows


def create_opening_voiceover(entry: dict, states: list[chess.Board],
                             moves: list[chess.Move], sans: list[str],
                             voice_path: Path) -> list[tuple[float, float]]:
    """Narrate a move while its piece moves, then hold the board during the explanation."""
    segments = make_opening_segments(entry, states, moves, sans)
    return create_segmented_voiceover(
        segments, voice_path, "opening_voice_segments",
        move_start_segment=1, move_count=len(moves),
    )


def create_puzzle_voiceover(script: str, pgn: str, puzzle_meta: dict,
                            voice_path: Path) -> list[tuple[float, float]]:
    """Hold the puzzle for the full think interval, then narrate and animate each solution move."""
    marker = "\n__PUZZLE_REVEAL__\n"
    if marker not in script:
        raise RuntimeError("Puzzle narration is missing its delayed solution-reveal marker.")
    intro, _legacy_solution = script.split(marker, 1)
    states, moves, sans, mate = renderer.parse_pgn(pgn, False)
    move_segments = [
        move_narration(states[index], move, sans[index])
        for index, move in enumerate(moves)
    ]
    primary_theme = puzzle_meta.get("primary_theme")
    if primary_theme:
        theme_label = re.sub(r"(?<!^)(?=[A-Z])", " ", str(primary_theme)).lower()
        outro = f"Key idea: {theme_label}. The line ends in checkmate. Follow Chess Bits for more puzzles."
    else:
        outro = "The line ends in checkmate. Calculate the opponent's best reply before choosing a move. Follow Chess Bits for more puzzles."
    # None inserts seven seconds of silence after the introduction. No solution move is narrated
    # or animated during that interval.
    segments: list[str | None] = [intro.strip(), None, *move_segments, outro]
    return create_segmented_voiceover(
        segments, voice_path, "puzzle_voice_segments",
        move_start_segment=2, move_count=len(moves),
    )


CLASSIC_PUZZLE_GAMES = [
    {
        "id": "classic-evergreen-combination",
        "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4 exd4 7. O-O d3 8. Qb3 Qf6 9. e5 Qg6 10. Re1 Nge7 11. Ba3 b5 12. Qxb5 Rb8 13. Qa4 Bb6 14. Nbd2 Bb7 15. Ne4 Qf5 16. Bxd3 Qh5 17. Nf6+ gxf6 18. exf6 Rg8 19. Rad1 Qxf3 20. Rxe7+ Nxe7 21. Qxd7+ Kxd7 22. Bf5+ Ke8 23. Bd7+ Kf8 24. Bxe7#",
        "start_ply": 32,
        "themes": ["queen sacrifice", "deflection", "mating attack", "battery"],
        "primary_theme": "deflection",
    },
    {
        "id": "classic-opera-combination",
        "pgn": "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8#",
        "start_ply": 18,
        "themes": ["deflection", "removal of defender", "rook battery", "sacrifice"],
        "primary_theme": "rook battery",
    },
    {
        "id": "classic-immortal-combination",
        "pgn": "1. e4 e5 2. f4 exf4 3. Bc4 Qh4+ 4. Kf1 b5 5. Bxb5 Nf6 6. Nf3 Qh6 7. d3 Nh5 8. Nh4 Qg5 9. Nf5 c6 10. g4 Nf6 11. Rg1 cxb5 12. h4 Qg6 13. h5 Qg5 14. Qf3 Ng8 15. Bxf4 Qf6 16. Nc3 Bc5 17. Nd5 Qxb2 18. Bd6 Bxg1 19. e5 Qxa1+ 20. Ke2 Na6 21. Nxg7+ Kd8 22. Qf6+ Nxf6 23. Be7#",
        "start_ply": 32,
        "themes": ["sacrifice", "deflection", "mating attack"],
        "primary_theme": "sacrifice",
    },
]


def puzzle_position_signature(fen: str) -> str:
    """Position fingerprint ignoring move counters, but keeping side, castling and en-passant state."""
    position = " ".join(fen.split()[:4])
    return hashlib.sha256(position.encode("utf-8")).hexdigest()


def puzzle_signature(fen: str, moves_uci: list[str]) -> str:
    """Solution fingerprint, paired with a position-only fingerprint to stop alternate-line repeats."""
    position = " ".join(fen.split()[:4])
    return hashlib.sha256((position + "|" + " ".join(moves_uci)).encode("utf-8")).hexdigest()


def build_classic_puzzle(template: dict) -> tuple[str, dict, list[str], str]:
    game = chess.pgn.read_game(__import__("io").StringIO(template["pgn"]))
    if game is None or game.errors:
        raise RuntimeError(f"Curated tactical game {template['id']} failed PGN parsing.")
    all_moves = list(game.mainline_moves())
    # Use only the final five plies of the verified mating line, so Shorts reveal
    # mate in at most three moves rather than replaying an entire classic game.
    start_ply = max(int(template["start_ply"]), len(all_moves) - 5)
    if start_ply < 0 or start_ply >= len(all_moves):
        raise RuntimeError(f"Curated tactical game {template['id']} has an invalid starting ply.")
    if len(all_moves) - start_ply not in (1, 3, 5):
        raise RuntimeError(f"Curated tactical puzzle {template['id']} is not mate in one, two or three.")
    board = game.board()
    for move in all_moves[:start_ply]:
        if move not in board.legal_moves:
            raise RuntimeError(f"Curated tactical game {template['id']} contains an illegal game move.")
        board.push(move)
    start_fen = board.fen()
    remaining = all_moves[start_ply:]
    sans = []
    uci_moves = []
    for move in remaining:
        if move not in board.legal_moves:
            raise RuntimeError(f"Curated tactical game {template['id']} contains an illegal solution move.")
        sans.append(board.san(move))
        uci_moves.append(move.uci())
        board.push(move)
    if not board.is_checkmate():
        raise RuntimeError(f"Curated tactical puzzle {template['id']} does not end in verified checkmate.")
    signature = puzzle_signature(start_fen, uci_moves)
    position_signature = puzzle_position_signature(start_fen)
    result = "0-1" if board.turn == chess.WHITE else "1-0"
    pgn = (
        f'[Event "Chess Bits Tactical Puzzle"]\n[Site "Chess Bits"]\n'
        f'[SetUp "1"]\n[FEN "{start_fen}"]\n[Result "{result}"]\n\n'
        + " ".join(sans) + f" {result}\n"
    )
    parsed_states, parsed_moves, parsed_sans, mate = renderer.parse_pgn(pgn, False)
    if len(parsed_moves) != len(remaining) or parsed_sans != sans or not mate:
        raise RuntimeError(f"Curated tactical puzzle {template['id']} failed round-trip and mate verification.")
    side = "White" if chess.Board(start_fen).turn == chess.WHITE else "Black"
    themes = list(template["themes"])
    script = (
        f"Here is a challenging chess puzzle. {side} is to move. "
        "Can you find the forcing continuation? Calculate checks, captures, and threats, and make sure you consider the opponent's strongest replies. "
        "\n__PUZZLE_REVEAL__\n"
        f"The solution is {', '.join(sans)}. "
        f"The key tactical ideas are {', '.join(themes)}. "
        "Follow the line to its verified final position and look at how the threats combine. "
        "Replay the sequence and try to solve it again without hints. Follow Chess Bits for more challenging chess puzzles."
    )
    return pgn, {
        "id": template["id"],
        "rating": None,
        "themes": themes,
        "primary_theme": template["primary_theme"],
        "mate": True,
        "source": "curated_classic_game",
        "signature": signature,
        "position_signature": position_signature,
        "source_date": None,
    }, sans, script


def validate_classic_puzzle_bank() -> None:
    marker_probe = make_puzzle_script(None, "White", ["deflection"], ["Qh7#"], True)
    if "\n__PUZZLE_REVEAL__\n" not in marker_probe:
        raise RuntimeError("Puzzle narration must preserve the delayed solution-reveal marker.")
    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()
    for template in CLASSIC_PUZZLE_GAMES:
        if template["id"] in seen_ids:
            raise RuntimeError(f"Duplicate curated puzzle ID: {template['id']}")
        pgn, meta, sans, script = build_classic_puzzle(template)
        if meta["signature"] in seen_signatures:
            raise RuntimeError("Two curated puzzles have the same position/solution fingerprint.")
        if len(sans) not in (1, 3, 5) or not script.startswith("Here is a challenging chess puzzle."):
            raise RuntimeError(f"Curated puzzle {template['id']} is not mate in one, two or three or has invalid narration.")
        seen_ids.add(template["id"])
        seen_signatures.add(meta["signature"])


def make_puzzle_script(rating: int | None, side: str, themes: list[str], sans: list[str], mate: bool) -> str:
    # Keep the hook short so the visual puzzle—not generic narration—does the work.
    mate_in = max(1, (len(sans) + 1) // 2)
    lead = f"{side} to move. Find mate in {mate_in}. Look for checks, captures, and threats."
    if rating is not None and rating >= 2400:
        lead = f"{side} to move. This is a difficult one: mate in {mate_in}. Calculate forcing moves."
    # The solution is assembled from verified SAN moves by create_puzzle_voiceover.
    return f"{lead}\n__PUZZLE_REVEAL__\nThe solution is {', '.join(sans)}."


def fetch_puzzle(target: date, used_ids: set[str], used_signatures: set[str],
                 used_position_signatures: set[str], recent_themes: set[str] | None = None,
                 puzzle_count: int = 0) -> tuple[str, dict, list[str], str]:
    """Choose from original curated tactical combinations and an open puzzle feed without naming its provider in the video."""
    recent_themes = recent_themes or set()
    classic_candidates = []
    for template in CLASSIC_PUZZLE_GAMES:
        if template["id"] in used_ids:
            continue
        try:
            candidate = build_classic_puzzle(template)
        except Exception as exc:
            print(f"CURATED_PUZZLE_REJECTED id={template['id']} type={type(exc).__name__}", flush=True)
            continue
        if candidate[1]["signature"] in used_signatures or candidate[1]["position_signature"] in used_position_signatures:
            continue
        if candidate[1]["primary_theme"] in recent_themes:
            continue
        classic_candidates.append((template, candidate))

    # Prefer difficult feed puzzles most of the time; use a curated classic
    # combination about every third Short for source variety, and as fallback.
    # Lichess /api/puzzle/daily serves the current daily puzzle; it does not
    # provide historical puzzles through a date query parameter. Do not pretend
    # that iterating dates yields a historical pool.
    prefer_classic = bool(classic_candidates) and puzzle_count % 3 == 0
    if prefer_classic:
        template, candidate = random.choice(classic_candidates)
        print(f"PUZZLE_SELECTED pool=curated position={template['id']}", flush=True)
        return candidate

    failures = []
    for offset in range(0, 1):
        puzzle_date = target
        # The daily endpoint is not a historical archive and its one puzzle is
        # often not a mate puzzle. Use Lichess's public, theme-filtered batch API
        # to obtain a small random sample of actual mate-in-1/2/3 puzzles.
        candidate_pool = []
        for angle in ("mateIn1", "mateIn2", "mateIn3"):
            try:
                batch_url = f"https://lichess.org/api/puzzle/batch/{angle}?nb=15"
                response = requests.get(
                    batch_url, timeout=(15, 45),
                    headers={"User-Agent": "ChessBitsAutoPublisher/1.0"},
                )
                response.raise_for_status()
                batch = response.json()
                for entry in batch.get("puzzles", []):
                    candidate_puzzle = entry.get("puzzle", {})
                    candidate_game = entry.get("game", {})
                    candidate_id = str(candidate_puzzle.get("id", ""))
                    candidate_rating = int(candidate_puzzle.get("rating") or 0)
                    candidate_solutions = candidate_puzzle.get("solution") or []
                    candidate_themes = [str(x) for x in candidate_puzzle.get("themes", [])]
                    if not candidate_id or candidate_id in used_ids:
                        failures.append(f"{angle}:missing-or-used")
                        continue
                    if candidate_rating < 1800:
                        failures.append(f"{angle}:rating-{candidate_rating}")
                        continue
                    if len(candidate_solutions) not in (1, 3, 5):
                        failures.append(f"{angle}:invalid-mate-line-length")
                        continue
                    if not any(x.lower() in {"matein1", "matein2", "matein3"} for x in candidate_themes):
                        failures.append(f"{angle}:missing-mate-theme")
                        continue
                    source_game = chess.pgn.read_game(__import__("io").StringIO(candidate_game.get("pgn", "")))
                    if source_game is None or source_game.errors:
                        failures.append(f"{angle}:invalid-source-pgn")
                        continue
                    source_moves = list(source_game.mainline_moves())
                    initial_ply = int(candidate_puzzle.get("initialPly", -1))
                    if initial_ply < 0 or initial_ply >= len(source_moves):
                        failures.append(f"{angle}:invalid-initial-ply")
                        continue
                    source_board = source_game.board()
                    prefix_legal = True
                    for source_move in source_moves[:initial_ply + 1]:
                        if source_move not in source_board.legal_moves:
                            prefix_legal = False
                            break
                        source_board.push(source_move)
                    if not prefix_legal:
                        failures.append(f"{angle}:illegal-source-prefix")
                        continue
                    start_fen = source_board.fen()
                    uci_moves = []
                    solution_legal = True
                    for uci in candidate_solutions:
                        try:
                            move = chess.Move.from_uci(uci)
                        except ValueError:
                            solution_legal = False
                            break
                        if move not in source_board.legal_moves:
                            solution_legal = False
                            break
                        uci_moves.append(move.uci())
                        source_board.push(move)
                    if not solution_legal or not source_board.is_checkmate():
                        failures.append(f"{angle}:solution-not-legal-checkmate")
                        continue
                    signature = puzzle_signature(start_fen, uci_moves)
                    position_signature = puzzle_position_signature(start_fen)
                    if signature in used_signatures or position_signature in used_position_signatures:
                        failures.append(f"{angle}:position-already-used")
                        continue
                    filtered_themes = [x for x in candidate_themes if x.lower() not in {"middlegame", "endgame", "short", "long"}][:5]
                    primary = next((x for x in filtered_themes if x in {
                        "deflection", "sacrifice", "pin", "skewer", "fork", "interference",
                        "discoveredAttack", "crushing", "doubleCheck",
                        "hangingPiece", "trappedPiece", "backRankMate", "promotion",
                    }), None)
                    if primary and primary in recent_themes:
                        failures.append(f"{angle}:recent-theme-{primary}")
                        continue
                    candidate_pool.append((candidate_rating, entry))
            except requests.RequestException as exc:
                failures.append(f"{angle}:{type(exc).__name__}")
        if candidate_pool:
            candidate_pool.sort(key=lambda item: item[0], reverse=True)
            _, selected = candidate_pool[0]
            puzzle = selected.get("puzzle", {})
            game_data = selected.get("game", {})
        else:
            puzzle = {}
            game_data = {}
        try:
            puzzle_id = str(puzzle.get("id", ""))
            if not puzzle_id or puzzle_id in used_ids:
                failures.append(f"{puzzle_date}:missing-or-used")
                continue
            rating = int(puzzle.get("rating") or 0)
            # Keep 2000+ as the preferred difficulty, but accept a valid 1800+
            # current daily puzzle when the endpoint offers no historical pool.
            if rating < 1800:
                failures.append(f"{puzzle_date}:rating-{rating}")
                continue
            game = chess.pgn.read_game(__import__("io").StringIO(game_data.get("pgn", "")))
            if game is None or game.errors:
                failures.append(f"{puzzle_date}:invalid-source-pgn")
                continue
            all_moves = list(game.mainline_moves())
            initial_ply = int(puzzle.get("initialPly", -1))
            # Include the move that creates the actual puzzle position, as defined by the feed's ply index.
            if initial_ply < 0 or initial_ply >= len(all_moves):
                failures.append(f"{puzzle_date}:invalid-initial-ply")
                continue
            board = game.board()
            for move in all_moves[:initial_ply + 1]:
                board.push(move)
            start_fen = board.fen()
            solutions = puzzle.get("solution") or []
            # Shorts are checkmate puzzles only: mate in one, two, or three at most.
            # A solver move plus a reply forms one full move; legal mating lines end on an odd ply.
            if len(solutions) not in (1, 3, 5):
                failures.append(f"{puzzle_date}:not-mate-in-1-2-3-ply-count")
                continue
            themes_raw = [str(theme) for theme in puzzle.get("themes", [])]
            if not any(theme.lower() in {"matein1", "matein2", "matein3"} for theme in themes_raw):
                failures.append(f"{puzzle_date}:not-tagged-mate-in-1-2-3")
                continue
            sans = []
            uci_moves = []
            invalid_solution = False
            for uci in solutions:
                try:
                    move = chess.Move.from_uci(uci)
                except ValueError:
                    invalid_solution = True
                    break
                if move not in board.legal_moves:
                    invalid_solution = True
                    break
                sans.append(board.san(move))
                uci_moves.append(move.uci())
                board.push(move)
            if invalid_solution:
                failures.append(f"{puzzle_date}:illegal-solution")
                continue
            pgn = (
                f'[Event "Chess Bits Tactical Puzzle"]\n[Site "Chess Bits"]\n'
                f'[SetUp "1"]\n[FEN "{start_fen}"]\n[Result "*"]\n\n'
                + " ".join(sans) + " *\n"
            )
            parsed_states, legal_moves, legal_sans, mate = renderer.parse_pgn(pgn, False)
            if len(legal_moves) != len(solutions) or legal_sans != sans or not mate:
                failures.append(f"{puzzle_date}:round-trip-or-checkmate-failed")
                continue
            signature = puzzle_signature(start_fen, uci_moves)
            position_signature = puzzle_position_signature(start_fen)
            if signature in used_signatures or position_signature in used_position_signatures:
                failures.append(f"{puzzle_date}:position-already-used")
                continue
            themes = [str(theme) for theme in puzzle.get("themes", []) if str(theme).lower() not in {"middlegame", "endgame", "short", "long"}][:5]
            primary = next((theme for theme in themes if theme in {
                "deflection", "sacrifice", "pin", "skewer", "fork", "interference",
                "discoveredAttack", "crushing", "doubleCheck",
                "hangingPiece", "trappedPiece", "backRankMate", "promotion",
            }), None)
            if primary and primary in recent_themes:
                failures.append(f"{puzzle_date}:recent-theme-{primary}")
                continue
            side = "White" if chess.Board(start_fen).turn == chess.WHITE else "Black"
            script = make_puzzle_script(rating, side, themes, sans, mate)
            return pgn, {
                "id": puzzle_id,
                "rating": rating,
                "themes": themes,
                "primary_theme": primary,
                "mate": mate,
                "source": "open_puzzle_feed",
                "signature": signature,
                "position_signature": position_signature,
                "source_date": None,
            }, sans, script
        except requests.RequestException as exc:
            failures.append(f"{puzzle_date}:{type(exc).__name__}")
            continue

    if classic_candidates:
        template, candidate = random.choice(classic_candidates)
        print(f"PUZZLE_SELECTED fallback=curated position={template['id']}", flush=True)
        return candidate
    raise RuntimeError("No unused high-difficulty puzzle passed the novelty, rating, length, and legality checks. " + ", ".join(failures[-20:]))


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
                 music_path: Path | None, thumbnail_path: Path,
                 move_windows: list[tuple[float, float]] | None = None) -> dict:
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
    if move_windows:
        # Never announce the final/checkmate state before the last narrated move has finished.
        reveal_end = min(duration - 0.25, max(reveal_end, move_windows[-1][1] + 0.25))
    # Save a clean initial-position frame for the YouTube thumbnail.
    thumb_frame = renderer.frame_at(mode, title, states, moves, sans, mate, 0.0, duration, reveal_end, move_windows)
    # Add a bold, readable title treatment to the generated board thumbnail.
    # Keep the board visible while giving the viewer a clear reason to click.
    from PIL import Image, ImageDraw, ImageFont
    thumb_frame = thumb_frame.convert("RGB")
    draw = ImageDraw.Draw(thumb_frame, "RGBA")
    w, h = thumb_frame.size
    band_h = int(h * (0.22 if mode == "puzzle_short" else 0.19))
    top = int(h * (0.04 if mode == "puzzle_short" else 0.05))
    draw.rounded_rectangle(
        (int(w * 0.035), top, int(w * 0.965), top + band_h),
        radius=max(12, int(w * 0.018)), fill=(7, 18, 30, 224),
        outline=(92, 210, 174, 245), width=max(2, int(w * 0.003))
    )
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_size = int(band_h * (0.32 if mode == "puzzle_short" else 0.29))
    try:
        font = ImageFont.truetype(font_path, font_size)
        font_is_scalable = True
    except OSError:
        font = ImageFont.load_default()
        font_is_scalable = False
    if mode == "puzzle_short":
        headline = title.upper().replace("| CHESS PUZZLE", "").strip()
        subline = "FIND THE WINNING MOVE"
        cue = "?"
    else:
        headline = title.upper()
        subline = "KEY IDEAS • PLANS • TACTICS"
        cue = "!"
    max_width = int(w * 0.68)
    while font_is_scalable and font.size > 12 and draw.textbbox((0, 0), headline, font=font)[2] > max_width:
        next_size = font.size - 2
        try:
            font = ImageFont.truetype(font_path, next_size)
        except OSError:
            font = ImageFont.load_default()
            font_is_scalable = False
    bbox = draw.textbbox((0, 0), headline, font=font)
    headline_y = top + int(band_h * 0.15)
    draw.text(((w - (bbox[2] - bbox[0])) / 2, headline_y), headline, font=font,
              fill=(255, 255, 255, 255), stroke_width=max(1, int(w * 0.0015)),
              stroke_fill=(0, 0, 0, 230))
    try:
        subfont = ImageFont.truetype(font_path, max(10, int(band_h * 0.17)))
    except OSError:
        subfont = ImageFont.load_default()
    subbbox = draw.textbbox((0, 0), subline, font=subfont)
    draw.text(((w - (subbbox[2] - subbbox[0])) / 2, top + int(band_h * 0.68)),
              subline, font=subfont, fill=(92, 240, 190, 255))
    # A small, high-contrast cue encourages the viewer to inspect the critical square
    # without obscuring the position or suggesting an unverified move.
    cuefont = ImageFont.truetype(font_path, max(16, int(band_h * 0.45))) if font_is_scalable else ImageFont.load_default()
    cue_x = int(w * 0.89)
    cue_y = int(top + band_h * 0.50)
    cue_bbox = draw.textbbox((0, 0), cue, font=cuefont)
    cue_w = cue_bbox[2] - cue_bbox[0]
    cue_h = cue_bbox[3] - cue_bbox[1]
    draw.ellipse((cue_x - cue_w, cue_y - cue_h, cue_x + cue_w, cue_y + cue_h),
                 fill=(232, 174, 58, 235), outline=(255, 255, 255, 240),
                 width=max(2, int(w * 0.002)))
    draw.text((cue_x - cue_w / 2, cue_y - cue_h / 2 - cue_bbox[1]),
              cue, font=cuefont, fill=(7, 18, 30, 255))
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
                frame = renderer.frame_at(mode, title, states, moves, sans, mate, index / renderer.FPS, duration, reveal_end, move_windows)
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
    parser.add_argument("--kind", choices=("opening", "puzzle"), help="Explicit content type for an authorized manual run.")
    parser.add_argument("--force-today", action="store_true", help="Permit one additional upload for today's date.")
    args = parser.parse_args()
    if args.force_today and args.kind != "puzzle":
        parser.error("--force-today is only allowed with --kind puzzle")

    state = load_state()
    target = today_ist() if args.force_today else next_target_date(state)
    if args.status_only:
        print(json.dumps({"needed": target is not None, "target_date": target.isoformat() if target else None}))
        return 0
    if args.self_test:
        renderer.load_pieces()
        validate_openings()
        validate_classic_puzzle_bank()
        validate_synchronized_animation()
        print(f"SELF_TEST_PASSED lessons={len(OPENINGS)} classic_puzzles={len(CLASSIC_PUZZLE_GAMES)} neo_pieces={len(renderer.PIECES)} narration_sync=true")
        return 0
    if target is None:
        print("SKIP: today's upload is already recorded; nothing is due.", flush=True)
        return 0

    kind = args.kind or next_kind(state)
    target_marker = marker_for(target, kind) if args.force_today else marker_for(target)
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
        print(f"CHESSBITS_PUBLISHED {json.dumps(row)}", flush=True)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    renderer.load_pieces()
    validate_openings()
    music_path = None
    music_meta = None
    puzzle_meta = None
    if kind == "opening":
        # Alternate opening lessons with a tactics-focused long-form lesson after every two openings.
        used_topics = {row.get("topic_id") for row in state.get("published", [])}
        longform_rows = [row for row in state.get("published", []) if row.get("kind") == "opening"]
        longform_count = len(longform_rows)
        # Keep regular openings/gambits as the backbone, but insert book-inspired
        # tactical lessons on varied dates rather than on a rigid predictable cycle.
        # The concepts are explained in original words; the book is a further-study reference.
        rng = random.Random(f"chessbits-tactics-antenna-{target.isoformat()}")
        tactical_due = longform_count >= 1 and rng.random() < 0.38
        want_tactics = tactical_due or (longform_count >= 2 and longform_count % 3 == 2)
        candidates = [
            row for row in OPENINGS
            if row["id"] not in used_topics and (row.get("lesson_type") == "tactics") == want_tactics
        ]
        if not candidates:
            candidates = [row for row in OPENINGS if row["id"] not in used_topics]
        entry = rng.choice(candidates) if candidates else OPENINGS[len(state.get("published", [])) % len(OPENINGS)]
        title = entry["title"]
        pgn = pgn_for_opening(entry)
        states, moves, sans, mate = renderer.parse_pgn(pgn, False)
        opening_entry = entry
        mode = "longform"
        topic_id = entry["id"]
        if entry.get("lesson_type") == "tactics":
            description = (
                f"{title}\n\nAn original, move-by-move Chess Bits tactics lesson. Learn how to spot candidate combinations by checking loose pieces, forcing moves, overloaded defenders, pins, deflections, interference, and mating threats. The demonstration line is legally checked; explanations are original and are not copied from a book.\n\n"
                f"Further study: {entry.get('book_reference', 'Tune Your Chess Tactics Antenna: Know When (and Where!) to Look for Winning Combinations')}.\n\n"
                "#Chess #ChessTactics #ChessBits"
            )
            tags = ["chess", "chess tactics", "chess combinations", "deflection", "sacrifice", "mating attack", "Chess Bits"]
        else:
            description = (
                f"{title}\n\nA practical chess opening lesson from Chess Bits. Follow the legal sample line, "
                "learn the strategic ideas, and practise the key decisions. Subscribe for more chess openings, "
                "gambits, tactics, and practical training.\n\n#Chess #ChessOpening #ChessBits"
            )
            tags = ["chess", "chess openings", "chess gambit", "chess strategy", "chess tutorial", "Chess Bits"]
    else:
        puzzle_count = sum(1 for row in state.get("published", []) if row.get("kind") == "puzzle")
        used_signatures = {row.get("puzzle_signature") for row in state.get("published", []) if row.get("puzzle_signature")}
        used_position_signatures = {row.get("puzzle_position_signature") for row in state.get("published", []) if row.get("puzzle_position_signature")}
        recent_themes = set()
        for row in [row for row in state.get("published", []) if row.get("kind") == "puzzle"][-4:]:
            theme = row.get("puzzle_primary_theme")
            if theme:
                recent_themes.add(theme)
        pgn, puzzle_meta, solution_sans, script = fetch_puzzle(
            target, used_puzzles, used_signatures, used_position_signatures, recent_themes, puzzle_count
        )
        mate_in = (len(solution_sans) + 1) // 2
        primary = str(puzzle_meta.get("primary_theme") or "")
        normalized_theme = re.sub(r"(?<!^)(?=[A-Z])", " ", primary).strip().lower()
        theme_title_options = {
            "deflection": [
                "Can You Deflect the Defender? | Mate in {n}",
                "The Defender Must Move | Mate in {n}",
                "One Deflection Opens the Mate | Mate in {n}",
            ],
            "sacrifice": [
                "Would You Sacrifice for Mate in {n}?",
                "The Sacrifice That Forces Mate in {n}",
                "Material Down, Mate in {n} | Can You Find It?",
            ],
            "pin": [
                "Spot the Pin That Forces Mate in {n}",
                "The Hidden Pin | Mate in {n}",
                "Can You Use This Pin to Find Mate in {n}?",
            ],
            "skewer": [
                "The Hidden Skewer | Mate in {n}",
                "Spot the Skewer Before Mate in {n}",
                "One Skewer, Then Mate in {n}",
            ],
            "fork": [
                "One Fork, Forced Mate in {n}?",
                "Spot the Fork That Leads to Mate in {n}",
                "The Fork Is the Clue | Mate in {n}",
            ],
            "interference": [
                "Break the Defence—Mate in {n}",
                "Find the Interference | Mate in {n}",
                "Cut the Defence, Find Mate in {n}",
            ],
            "discovered attack": [
                "Find the Discovered Attack | Mate in {n}",
                "The Hidden Attack Before Mate in {n}",
                "Can You Spot the Discovered Attack?",
            ],
            "double check": [
                "Double Check—Can You Force Mate in {n}?",
                "The Double-Check Clue | Mate in {n}",
                "Spot the Double Check Before Mate",
            ],
            "hanging piece": [
                "The Loose Defender | Mate in {n}",
                "Spot the Hanging Piece—Mate in {n}",
                "One Loose Piece, Mate in {n}",
            ],
            "trapped piece": [
                "Trap the Defender: Mate in {n}",
                "The Trapped Piece Is the Clue | Mate in {n}",
                "Can You Exploit the Trapped Piece?",
            ],
            "back rank mate": [
                "Spot the Back-Rank Weakness | Mate in {n}",
                "Back-Rank Trouble: Find Mate in {n}",
                "Can You Punish the Weak Back Rank?",
            ],
            "promotion": [
                "Promotion Threat or Mate in {n}?",
                "The Promotion Clue | Mate in {n}",
                "Can You Find the Winning Promotion Tactic?",
            ],
            "removal of defender": [
                "Remove the Defender | Mate in {n}",
                "Can You Eliminate the Key Defender?",
                "The Defender Must Fall—Mate in {n}",
            ],
            "rook battery": [
                "The Rook Battery | Mate in {n}",
                "Spot the Battery Before Mate in {n}",
                "Two Rooks, One Forced Mate",
            ],
            "queen sacrifice": [
                "Would You Give Up the Queen for Mate in {n}?",
                "The Queen Sacrifice That Forces Mate",
                "Find the Queen Sacrifice | Mate in {n}",
            ],
        }
        options = theme_title_options.get(normalized_theme) or [
            "Can You Find Mate in {n}? | Chess Puzzle",
            "One Winning Line: Mate in {n} Moves",
            "Find the Hidden Mate in {n} Moves",
            "Only One Line Wins: Mate in {n}",
        ]
        title_seed = int(hashlib.sha256(str(puzzle_meta.get("id", target.isoformat())).encode("utf-8")).hexdigest()[:8], 16)
        title = options[title_seed % len(options)].format(n=mate_in)
        mode = "puzzle_short"
        topic_id = "puzzle-" + puzzle_meta["id"]
        rating_note = f"Difficulty rating: {puzzle_meta['rating']}.\n" if puzzle_meta.get("rating") is not None else ""
        description = (
            "A challenging chess puzzle. Pause before the solution reveal and calculate every reply.\n"
            + rating_note
            + "The solution is revealed only after the thinking interval. Themes: "
            + ", ".join(puzzle_meta["themes"]) + ".\n\n"
        )
        try:
            music_path, music_meta = download_short_music(target, OUT_DIR / "short_music.mp3")
            description += music_meta["credit"] + "\n\n#chess #puzzle #chesstactics"
        except Exception as music_exc:
            # Music is a Shorts-only enhancement, never a reason to miss the daily upload.
            music_path, music_meta = None, None
            description += "#chess #puzzle #chesstactics"
            print(f"SHORT_MUSIC_UNAVAILABLE publishing_without_music type={type(music_exc).__name__}", flush=True)
        tags = ["chess", "chess puzzle", "checkmate in 1", "checkmate in 2", "checkmate in 3", "chess shorts", "Chess Bits"]

    voice_path = OUT_DIR / "voiceover.wav"
    video_path = OUT_DIR / "chess-bits-daily.mp4"
    move_windows = None
    if puzzle_meta:
        move_windows = create_puzzle_voiceover(script, pgn, puzzle_meta, voice_path)
        print("PUZZLE_THINK_TIMER seconds=7 solution_voiceover_delayed=true", flush=True)
    else:
        if not opening_entry:
            raise RuntimeError("Opening metadata is missing for synchronized narration.")
        move_windows = create_opening_voiceover(opening_entry, states, moves, sans, voice_path)
    thumbnail_path = OUT_DIR / "start-position.jpg"
    qa = render_video(pgn, mode, title, voice_path, video_path, music_path, thumbnail_path, move_windows)
    if puzzle_meta:
        tags = tags + ["ChessBitsPuzzle", "ChessBitsPuzzleId:" + str(puzzle_meta["id"])]
    elif opening_entry and opening_entry.get("lesson_type") == "tactics":
        tags = tags + ["ChessBitsTactics", "ChessBitsTopic:" + str(topic_id)]
    else:
        tags = tags + ["ChessBitsOpening", "ChessBitsTopic:" + str(topic_id)]
    video_id, verified, thumbnail_set = publish_video(
        service, uploads_playlist, video_path, title, description, tags, target, mode == "puzzle_short", thumbnail_path, target_marker
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
        "puzzle_signature": puzzle_meta.get("signature") if puzzle_meta else None,
        "puzzle_position_signature": puzzle_meta.get("position_signature") if puzzle_meta else None,
        "puzzle_source": puzzle_meta.get("source") if puzzle_meta else None,
        "puzzle_themes": puzzle_meta.get("themes", []) if puzzle_meta else [],
        "puzzle_primary_theme": puzzle_meta.get("primary_theme") if puzzle_meta else None,
        "music_track": music_meta["id"] if music_meta else None,
        "start_position_thumbnail_set": thumbnail_set,
    }
    state.setdefault("published", []).append(row)
    state["published"] = sorted(state["published"], key=lambda item: item["target_date"])[-400:]
    save_state(state)
    # No success email by design. The workflow sends an email only when publication fails.
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
