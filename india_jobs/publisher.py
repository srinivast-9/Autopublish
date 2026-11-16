#!/usr/bin/env python3
"""Free, official-source-first India-wide mass-recruitment video publisher.

FreeJobAlert is read only as a discovery feed. No FreeJobAlert article copy,
images, URLs, descriptions, or branding are published. A candidate is accepted
only after an official recruiting-organisation URL/PDF is found and verified.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import edge_tts
import fitz
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "india_jobs/settings.json").read_text(encoding="utf-8"))
STATE_PATH = ROOT / "state/india_jobs.json"
WORK = ROOT / "output/india_jobs"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
TIMEOUT = 25
USER_AGENT = "BharatHiringBrief/1.0 (recruitment-notice verification; contact via repository)"

STATE_NAMES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand",
    "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh",
    "uttarakhand", "west bengal"
]
STATE_ONLY_PATTERNS = [
    r"state[- ]wise vacancies only", r"domicile.*mandatory",
    r"resident of .*only", r"state cadre", r"district cadre",
    r"candidates belonging to .*only", r"local resident.*only"
]
ALL_INDIA_PATTERNS = [
    r"all[- ]india", r"pan[- ]india", r"across india",
    r"anywhere in india", r"all over india",
    r"candidates from any state", r"eligible candidates from across"
]
DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
                "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

def log(message: str) -> None:
    print(f"[IndiaJobs] {message}", flush=True)

def load_state() -> dict:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return {"done": {}, "pending": None}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        data.setdefault("done", {})
        data.setdefault("pending", None)
        return data
    except Exception:
        raise RuntimeError("Publishing ledger is invalid; refusing to risk duplicate uploads.")

def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)

def host_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme != "https" or not host or p.username or p.password:
            return False
        if host == "freejobalert.com" or host.endswith(".freejobalert.com"):
            return False
        trusted = set(CONFIG["trusted_domains"]) | set(CONFIG["known_national_hosts"])
        return any(host == d or host.endswith("." + d) for d in trusted)
    except Exception:
        return False

def safe_get(url: str) -> requests.Response:
    if not host_allowed(url):
        raise ValueError("URL is not on the approved official-domain list")
    response = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, stream=False)
    if not host_allowed(response.url):
        raise ValueError("Official URL redirected outside the approved domain list")
    response.raise_for_status()
    return response

def official_links_from_discovery(article_url: str) -> list[str]:
    p = urlparse(article_url)
    if p.scheme != "https" or not ((p.hostname or "").lower() == "freejobalert.com"
            or (p.hostname or "").lower().endswith(".freejobalert.com")):
        raise ValueError("Discovery entry is not from the configured source")
    response = SESSION.get(article_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    final_host = (urlparse(response.url).hostname or "").lower()
    if final_host != "freejobalert.com" and not final_host.endswith(".freejobalert.com"):
        raise ValueError("Discovery page redirected to an unexpected host")
    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    anchors = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(response.url, anchor["href"].strip())
        if host_allowed(url) and url not in found:
            label = anchor.get_text(" ", strip=True).lower()
            priority = 0 if re.search(r"official|notification|advertisement|apply online|pdf|recruitment", label) else 1
            anchors.append((priority, url))
    anchors.sort(key=lambda item: item[0])
    return [url for _, url in anchors[:CONFIG["max_official_links_to_check"]]]

def extract_official_content(url: str) -> tuple[str, str, str]:
    response = safe_get(url)
    content_type = (response.headers.get("content-type") or "").lower()
    raw = response.content
    final_url = response.url
    if "pdf" in content_type or raw[:4] == b"%PDF":
        doc = fitz.open(stream=raw, filetype="pdf")
        chunks = [page.get_text("text") for page in doc]
        text = "\n".join(chunks)
        if len(text.strip()) < 300:
            raise ValueError("Official PDF appears image-only or has insufficient extractable text")
        title = next((x.strip() for x in text.splitlines() if len(x.strip()) > 8), "Official recruitment notice")
        return text, title, final_url
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    # Prefer an official application/notification link found on the official page itself.
    for a in soup.find_all("a", href=True):
        target = urljoin(final_url, a["href"])
        if host_allowed(target) and re.search(r"apply|notification|advertisement|recruitment", a.get_text(" ", strip=True), re.I):
            return text, title, target
    return text, title, final_url

def parse_vacancies(text: str, title: str) -> int | None:
    patterns = [
        r"(?:total\s+(?:number\s+of\s+)?(?:vacancies|posts|seats|engagements))\D{0,35}([0-9][0-9,]{1,8})",
        r"(?:vacancies|posts|seats)\s*[:\-–]?\s*([0-9][0-9,]{1,8})\s*\(?(?:total|in total)",
        r"(?:advertised|notified)\s+posts\D{0,25}([0-9][0-9,]{1,8})"
    ]
    candidates = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            n = int(match.group(1).replace(",", ""))
            if 1 <= n <= 500000:
                candidates.append(n)
    if candidates:
        return max(candidates)
    m = re.search(r"\b([0-9][0-9,]{2,8})\s+(?:vacancies|posts|apprentices|seats)\b", title, re.I)
    return int(m.group(1).replace(",", "")) if m else None

def find_field(text: str, labels: list[str], max_chars: int = 380) -> str:
    lines = [re.sub(r"\s+", " ", x).strip(" :-\t") for x in text.splitlines()]
    for i, line in enumerate(lines):
        if any(re.search(label, line, re.I) for label in labels):
            window = " ".join(x for x in lines[i:i+4] if x)
            window = re.sub(r"\s+", " ", window).strip()
            if window:
                return window[:max_chars]
    return ""

def parse_deadline(text: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    for i, line in enumerate(lines):
        if re.search(r"last date|closing date|apply online up to|closing of online application|last date for submission", line, re.I):
            window = " ".join(lines[i:i+3])
            for fmt in DATE_FORMATS:
                match = re.search(r"(\d{1,2}[ /.-][A-Za-z0-9]{1,9}[ /.-]\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})", window)
                if match:
                    for candidate in (match.group(1), match.group(1).replace("  ", " ")):
                        try:
                            d = None
                            for f in DATE_FORMATS:
                                try:
                                    d = datetime.strptime(candidate, f).date()
                                    break
                                except ValueError:
                                    pass
                            if d:
                                return d.isoformat()
                        except Exception:
                            continue
    return ""

def category_for(text: str, host: str) -> str:
    s = (text + " " + host).lower()
    if re.search(r"railway|\brrb\b|\brpf\b", s): return "RAILWAY"
    if re.search(r"bank|\bibps\b|\bsbi\b|\brbi\b|\bnabard\b|\bsidbi\b", s): return "BANKS"
    if re.search(r"ongc|iocl|ntpc|powergrid|coal india|gail|bhel|sail|aai|nhpc|psu|public sector", s): return "PSU"
    if re.search(r"army|navy|air force|defence|defense|crpf|bsf|cisf|itbp", s): return "DEFENCE"
    if re.search(r"isro|drdo|scientific|research|technical", s): return "SCIENCE & RESEARCH"
    return "CENTRAL GOVERNMENT"

def is_india_wide(text: str, title: str, host: str) -> bool:
    combined = (title + "\n" + text).lower()
    if any(re.search(p, combined, re.I) for p in STATE_ONLY_PATTERNS):
        return False
    explicit = any(re.search(p, combined, re.I) for p in ALL_INDIA_PATTERNS)
    national_hosts = set(CONFIG["known_national_hosts"])
    trusted = set(CONFIG["trusted_domains"])
    nationally_scoped = any(host == h or host.endswith("." + h) for h in national_hosts | trusted)
    state_in_title = any(re.search(r"\b" + re.escape(s) + r"\b", title.lower()) for s in STATE_NAMES)
    return explicit or (nationally_scoped and not state_in_title)

def organisation_name(host: str) -> str:
    known = {
        "ibps.in": "Institute of Banking Personnel Selection",
        "sbi.co.in": "State Bank of India",
        "rbi.org.in": "Reserve Bank of India",
        "upsc.gov.in": "Union Public Service Commission",
        "ssc.gov.in": "Staff Selection Commission",
        "indianrailways.gov.in": "Indian Railways",
        "rrbcdg.gov.in": "Railway Recruitment Board",
        "ongcindia.com": "Oil and Natural Gas Corporation",
        "iocl.com": "Indian Oil Corporation",
        "ntpc.co.in": "NTPC",
        "drdo.gov.in": "Defence Research and Development Organisation",
        "isro.gov.in": "Indian Space Research Organisation",
        "powergrid.in": "POWERGRID"
    }
    for domain, name in known.items():
        if host == domain or host.endswith("." + domain):
            return name
    labels = host.split(".")
    return labels[-2].replace("-", " ").replace("_", " ").title() if len(labels) > 1 else host.title()

def role_from_notice(text: str, official_title: str) -> str:
    candidates = [re.sub(r"\s+", " ", x).strip(" :-") for x in text.splitlines()[:45]]
    patterns = [r"(?:recruitment|engagement|appointment|selection)\s+(?:of|for)\s+(.{5,100})",
                r"(?:notification|advertisement)\s+for\s+(.{5,100})"]
    for line in candidates:
        for pattern in patterns:
            m = re.search(pattern, line, re.I)
            if m:
                return m.group(1).strip(" .:-")[:90]
    clean = re.sub(r"\s+", " ", official_title).strip()
    return clean[:90] if clean else "Multiple posts"

def candidate_job(entry) -> tuple[dict | None, str]:
    article_url = entry.get("link", "")
    links = official_links_from_discovery(article_url)
    if not links:
        return None, "No approved recruiting-organisation link was present"
    errors = []
    for link in links:
        try:
            text, official_title, source_url = extract_official_content(link)
            host = (urlparse(source_url).hostname or "").lower()
            if not host_allowed(source_url):
                continue
            vacancies = parse_vacancies(text, official_title)
            if vacancies is None or vacancies < CONFIG["min_vacancies"]:
                continue
            if not is_india_wide(text, official_title, host):
                continue
            deadline = parse_deadline(text)
            if deadline and date.fromisoformat(deadline) < datetime.now(ZoneInfo('Asia/Kolkata')).date():
                continue
            org = organisation_name(host)
            category = category_for(official_title + " " + text[:3000], host)
            role = role_from_notice(text, official_title)
            apply_hint = find_field(text, [r"how to apply", r"application process", r"apply online"], 280)
            qualification = find_field(text, [r"educational qualification", r"essential qualification", r"minimum qualification", r"eligibility criteria"], 320)
            age = find_field(text, [r"age limit", r"upper age", r"age criteria"], 260)
            pay = find_field(text, [r"pay scale", r"salary", r"remuneration", r"pay level"], 260)
            selection = find_field(text, [r"selection process", r"method of selection", r"selection procedure"], 260)
            key = hashlib.sha256((source_url + "|" + str(vacancies) + "|" + role).encode()).hexdigest()[:20]
            return {
                "key": key, "organisation": org, "role": role,
                "category": category, "vacancies": vacancies,
                "deadline": deadline, "qualification": qualification,
                "age": age, "pay": pay, "selection": selection,
                "apply_hint": apply_hint, "official_url": source_url,
                "official_title": official_title[:160],
                "verified_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"
            }, "accepted"
        except Exception as exc:
            errors.append(str(exc)[:180])
    if errors and len(errors) == len(links):
        raise RuntimeError("; ".join(errors))
    return None, "No notice passed the vacancy, nationwide-scope and official-source checks"

def scripts_for(job: dict, long_url: str = "") -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    org = job["organisation"]
    role = job["role"]
    count = f'{job["vacancies"]:,}'
    deadline = date.fromisoformat(job["deadline"]).strftime("%d %B %Y") if job.get("deadline") else "not clearly stated in the extracted notice text"
    qualification = job.get("qualification") or "The qualification section must be checked directly in the official notification."
    age = job.get("age") or "The age criteria were not reliably extracted; confirm the category-wise limits in the official notice."
    pay = job.get("pay") or "The pay or stipend details should be confirmed from the official notification."
    selection = job.get("selection") or "The selection stages are set out in the official notice and must be checked before applying."
    apply_hint = job.get("apply_hint") or "Use the organisation's official recruitment page and follow the instructions in the notification."
    long = [
      ("NATIONWIDE HIRING ALERT", f'{org} has an India-wide recruitment update covering {count} vacancies for {role}. This briefing explains the important details, the checks candidates should make, and where to apply. We use the recruiting organisation’s own notice as the source of truth.'),
      (f'{job["category"]} • {org}', f'This opening is classified under {job["category"]}. The notified opportunity is for {role}. Check the post names and vacancy distribution in the official document because a large total can include different disciplines, categories, or locations.'),
      ("WHO SHOULD CHECK THIS OPENING", f'Qualification information from the notice: {qualification}. Age information: {age}. These are extracts to help you find the right sections quickly, not a substitute for checking the full notification. Confirm relaxations, reservation rules, experience requirements, and document conditions for your own category.'),
      ("SALARY AND SELECTION", f'Pay or stipend information: {pay}. Selection information: {selection}. Do not assume every post has the same pay, exam, interview, or skill test. The recruiting organisation may use different stages for different roles, so match your chosen post to its specific instructions.'),
      ("IMPORTANT DEADLINE", f'The last date identified in the official notice is {deadline}. Check the recruitment portal for any corrigendum or extension before submitting. Apply early enough to complete registration, upload documents, pay any official fee where applicable, and save the final submitted application and receipt.'),
      ("HOW TO APPLY SAFELY", f'{apply_hint}. Open the official recruitment link shown in this video’s description. Confirm the organisation name and web address before entering personal information. Never pay an agent, use an unofficial form, or share an OTP with anyone claiming to guarantee selection.'),
      ("CANDIDATE CHECKLIST", "Before you apply, check the exact post code, education and subject requirements, age on the specified cut-off date, category certificates, experience, fee exemptions, exam pattern, and document formats. Keep a copy of the notification and the application confirmation. A vacancy count alone does not establish that every candidate is eligible."),
      ("OFFICIAL SOURCE ONLY", "The direct recruiting-organisation notification and application page are linked in the description. Read the complete notice before making a decision. This channel provides an independent informational summary and is not affiliated with the employer. Subscribe for verified India-wide bank, central government, PSU, railway, and defence recruitment briefings.")
    ]
    short = [
      ("BIG INDIA-WIDE RECRUITMENT", f'{org} has announced {count} vacancies for {role}. This is a nationwide opportunity in the {job["category"]} category.'),
      ("CHECK ELIGIBILITY FIRST", f'Qualification: {qualification[:210]} Age: {age[:150]}'),
      ("DON’T MISS THE DEADLINE", f'Last date found in the official notice: {deadline}. The complete breakdown, selection details, and direct official application link are in the full video linked here. Apply only through the recruiting organisation’s verified website.')
    ]
    return long, short

def font(size: int, bold: bool = False):
    candidates = [
      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
      "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
    ]
    for path in candidates:
        if Path(path).exists(): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False))

def make_slide(path: Path, heading: str, body: str, category: str, vertical: bool) -> None:
    w, h = (1080, 1920) if vertical else (1920, 1080)
    image = Image.new("RGB", (w, h), (10, 18, 34))
    d = ImageDraw.Draw(image)
    for y in range(h):
        v = int(15 + 22 * y / h)
        d.line((0, y, w, y), fill=(v, v + 6, v + 18))
    accent = (255, 190, 65)
    d.rounded_rectangle((w*0.055, h*0.055, w*0.945, h*0.945), radius=38, outline=(54, 81, 117), width=4)
    d.rounded_rectangle((w*0.075, h*0.075, w*0.925, h*0.15), radius=24, fill=(24, 43, 72))
    d.text((w*0.105, h*0.092), CONFIG["brand"].upper(), font=font(int(w*0.026), True), fill=(240, 245, 255))
    tag = category.upper()
    d.rounded_rectangle((w*0.075, h*0.18, w*0.43, h*0.235), radius=18, fill=(16, 113, 111))
    d.text((w*0.095, h*0.19), tag, font=font(int(w*0.023), True), fill="white")
    heading_font = font(int(w*(0.052 if vertical else 0.047)), True)
    body_font = font(int(w*(0.031 if vertical else 0.027)))
    margin = int(w*0.09)
    head_y = int(h*0.29)
    d.multiline_text((margin, head_y), wrap(heading, 23 if vertical else 38), font=heading_font, fill=accent, spacing=16)
    body_y = int(h*0.48 if vertical else h*0.47)
    d.multiline_text((margin, body_y), wrap(body, 31 if vertical else 65), font=body_font, fill=(230, 237, 248), spacing=18)
    d.line((margin, int(h*0.88), w-margin, int(h*0.88)), fill=(65, 90, 122), width=3)
    d.text((margin, int(h*0.90)), "VERIFY THE NOTICE • APPLY ON THE OFFICIAL PORTAL", font=font(int(w*0.017), True), fill=(164, 184, 210))
    image.save(path, quality=94)

async def make_voice(text: str, target: Path) -> None:
    speaker = edge_tts.Communicate(text, CONFIG["voice"], rate="+0%", volume="+0%")
    await speaker.save(str(target))

def probe_duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True)
    return max(1.5, float(out.strip()))

def render_scenes(scenes: list[tuple[str, str]], directory: Path, vertical: bool, category: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    clips = []
    w, h = (1080, 1920) if vertical else (1920, 1080)
    for i, (heading, body) in enumerate(scenes):
        image_path = directory / f"slide_{i:02d}.jpg"
        audio_path = directory / f"voice_{i:02d}.mp3"
        clip_path = directory / f"clip_{i:02d}.mp4"
        make_slide(image_path, heading, body, "INDIA-WIDE JOBS", vertical)
        asyncio.run(make_voice(f"{heading}. {body}", audio_path))
        duration = probe_duration(audio_path)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},zoompan=z='min(zoom+0.00035,1.045)':d=1:s={w}x{h}:fps=30,format=yuv420p"
        subprocess.run([
          "ffmpeg","-y","-hide_banner","-loglevel","error",
          "-loop","1","-i",str(image_path),"-i",str(audio_path),
          "-vf",vf,"-t",str(duration+0.25),"-r","30",
          "-c:v","libx264","-preset","veryfast","-tune","stillimage",
          "-c:a","aac","-b:a","128k","-shortest",str(clip_path)
        ], check=True)
        clips.append(clip_path)
    list_path = directory / "concat.txt"
    list_path.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    output = directory / ("video_short.mp4" if vertical else "video_long.mp4")
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0",
                    "-i",str(list_path),"-c","copy","-movflags","+faststart",str(output)], check=True)
    # Decode every frame before the API upload; damaged media must never be published.
    subprocess.run(["ffmpeg","-v","error","-i",str(output),"-f","null","-"], check=True)
    return output

def make_thumbnail(path: Path, job: dict, vertical: bool) -> None:
    w, h = (720, 1280) if vertical else (1280, 720)
    im = Image.new("RGB", (w, h), (8, 17, 34))
    d = ImageDraw.Draw(im)
    for y in range(h):
        v = int(15 + 30*y/h)
        d.line((0,y,w,y), fill=(v, v+7, v+20))
    d.rounded_rectangle((24,24,w-24,h-24), radius=36, outline=(59,93,135), width=5)
    d.rounded_rectangle((52,54,w-52,145 if not vertical else 170), radius=24, fill=(21,47,76))
    d.text((78,82), CONFIG["brand"].upper(), font=font(34 if not vertical else 30, True), fill="white")
    d.rounded_rectangle((52,170 if not vertical else 205,w-52,250 if not vertical else 300), radius=20, fill=(14,120,112))
    d.text((78,190 if not vertical else 225), job["category"], font=font(34,True), fill="white")
    big = font(104 if not vertical else 88, True)
    d.text((72,300 if not vertical else 390), f'{job["vacancies"]:,}', font=big, fill=(255,195,65))
    d.text((78,430 if not vertical else 520), "VACANCIES • INDIA-WIDE", font=font(32 if not vertical else 28,True), fill=(238,243,251))
    role = wrap(job["role"], 25 if not vertical else 17)
    d.multiline_text((78,500 if not vertical else 620), role, font=font(39 if not vertical else 37,True), fill=(235,241,251), spacing=10)
    d.text((78,h-105), job["organisation"][:48], font=font(25,True), fill=(163,190,222))
    im.save(path, quality=95)

def credentials():
    required = ["JOBS_YOUTUBE_CLIENT_ID","JOBS_YOUTUBE_CLIENT_SECRET",
                "JOBS_YOUTUBE_REFRESH_TOKEN","JOBS_YOUTUBE_CHANNEL_ID"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing one-time GitHub Actions secrets: " + ", ".join(missing))
    creds = Credentials(
      None, refresh_token=os.environ["JOBS_YOUTUBE_REFRESH_TOKEN"],
      token_uri="https://oauth2.googleapis.com/token",
      client_id=os.environ["JOBS_YOUTUBE_CLIENT_ID"],
      client_secret=os.environ["JOBS_YOUTUBE_CLIENT_SECRET"],
      scopes=SCOPES
    )
    creds.refresh(Request())
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    channels = service.channels().list(part="id", mine=True, maxResults=50).execute()
    ids = {x["id"] for x in channels.get("items", [])}
    expected = os.environ["JOBS_YOUTUBE_CHANNEL_ID"]
    if expected not in ids:
        raise RuntimeError("OAuth is not authorised for the configured jobs channel; refusing to upload to another channel.")
    return service

def upload_video(service, video: Path, title: str, description: str, tags: list[str], on_uploaded=None) -> str:
    # Stage privately so the actual destination channel can be checked before
    # the video becomes public.
    body = {
      "snippet": {"title": title[:100], "description": description[:4900],
                  "tags": tags[:30], "categoryId": CONFIG["long_video_category_id"],
                  "defaultLanguage": "en"},
      "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8*1024*1024, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Upload progress: {int(status.progress()*100)}%")
    if not response or not response.get("id"):
        raise RuntimeError("YouTube did not return a video ID")
    video_id = response["id"]
    expected_channel = os.environ["JOBS_YOUTUBE_CHANNEL_ID"]
    actual_channel = response.get("snippet", {}).get("channelId")
    if actual_channel != expected_channel:
        raise RuntimeError(
            f"Upload {video_id} landed on channel {actual_channel!r}, not the configured jobs channel; "
            "the video was kept private and was not made public."
        )
    # Record the ID immediately after the private upload so a later API failure
    # can be retried without creating another copy.
    if on_uploaded:
        on_uploaded(video_id)
    return video_id

def make_public_after_verification(service, video_id: str) -> None:
    expected_channel = os.environ["JOBS_YOUTUBE_CHANNEL_ID"]
    data = service.videos().list(part="snippet,status,processingDetails", id=video_id).execute()
    rows = data.get("items", [])
    if not rows:
        raise RuntimeError(f"YouTube could not find uploaded video {video_id}")
    item = rows[0]
    actual_channel = item.get("snippet", {}).get("channelId")
    if actual_channel != expected_channel:
        raise RuntimeError(f"Video {video_id} belongs to channel {actual_channel!r}, not the configured jobs channel.")
    status = item.get("status", {})
    if status.get("privacyStatus") != "public":
        processing = item.get("processingDetails", {}).get("processingStatus", "")
        if processing in {"failed", "terminated"}:
            raise RuntimeError(f"YouTube processing failed for video {video_id}: {processing}")
        if processing != "succeeded":
            return
        service.videos().update(
            part="status",
            body={"id": video_id, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        ).execute()

def wait_public(service, video_id: str) -> None:
    for _ in range(24):
        make_public_after_verification(service, video_id)
        data = service.videos().list(part="snippet,status,processingDetails", id=video_id).execute()
        rows = data.get("items", [])
        if rows:
            item = rows[0]
            if item.get("snippet", {}).get("channelId") != os.environ["JOBS_YOUTUBE_CHANNEL_ID"]:
                raise RuntimeError(f"Video {video_id} channel ID changed or did not match.")
            status = item.get("status", {})
            if status.get("privacyStatus") == "public":
                return
            if status.get("uploadStatus") == "rejected":
                raise RuntimeError(f"YouTube rejected video {video_id}")
        time.sleep(15)
    raise RuntimeError(f"Video {video_id} was not confirmed public; it remains private until verified.")

def set_thumbnail(service, video_id: str, image_path: Path) -> None:
    service.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(image_path), mimetype="image/jpeg")).execute()

def descriptions(job: dict, long_id: str) -> tuple[str, str, str, str]:
    long_url = f"https://www.youtube.com/watch?v={long_id}"
    direct = job["official_url"]
    due = date.fromisoformat(job["deadline"]).strftime("%d %B %Y") if job.get("deadline") else "Check the official notice"
    common = (
      f"\n\nOFFICIAL RECRUITMENT SOURCE\n{direct}\n\n"
      f"Category: {job['category']} | Vacancies: {job['vacancies']:,} | Closing date: {due}\n"
      "This independently prepared video is an informational summary. Read the complete official notification, "
      "check for corrigenda, and confirm your eligibility before applying. Never pay agents or use unofficial forms."
    )
    long_desc = (
      f"India-wide recruitment briefing: {job['organisation']} – {job['role']}.\n"
      "The video explains the vacancy scale, eligibility checks, age/pay/selection details where extractable, "
      "the application deadline and a safe-application checklist." + common
    )
    short_desc = (
      f"Quick alert: {job['organisation']} – {job['vacancies']:,} India-wide vacancies.\n"
      f"FULL VIDEO: {long_url}\n" + common + "\n#Shorts #IndiaJobs #GovernmentJobs"
    )
    long_title = f"{job['category']}: {job['organisation']} {job['role']} – {job['vacancies']:,} Posts | India-Wide"
    short_title = f"{job['organisation']}: {job['vacancies']:,} India-Wide Vacancies! #Shorts"
    return long_title[:100], long_desc, short_title[:100], short_desc

def run_one(service, state: dict, job: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    pending = state["pending"]
    key = job["key"]
    folder = WORK / key
    folder.mkdir(parents=True, exist_ok=True)
    long_scenes, short_scenes = scripts_for(job)
    long_file = folder / "long.mp4"
    long_thumb = folder / "long-thumb.jpg"
    short_file = folder / "short.mp4"
    short_thumb = folder / "short-thumb.jpg"

    # GitHub-hosted runners are ephemeral. Recreate thumbnail files after a
    # retry even when the corresponding YouTube video ID was saved previously.
    if not long_thumb.exists():
        make_thumbnail(long_thumb, job, False)
    if not short_thumb.exists():
        make_thumbnail(short_thumb, job, True)

    if not pending.get("long_id"):
        if not long_file.exists():
            long_file = render_scenes(long_scenes, folder / "render-long", False, job["category"])
            long_file.replace(folder / "long.mp4")
        make_thumbnail(long_thumb, job, False)
        long_title, long_desc, _, _ = descriptions(job, "pending")
        def remember_long(video_id: str) -> None:
            pending["long_id"] = video_id
            save_state(state)
        video_id = upload_video(service, folder / "long.mp4", long_title, long_desc,
                                ["India jobs", "central government jobs", "PSU jobs", "bank jobs", "railway jobs"],
                                on_uploaded=remember_long)
        pending["long_id"] = video_id
        save_state(state)
        log(f"Long-form upload created: {video_id}")
    wait_public(service, pending["long_id"])
    if not pending.get("long_thumb"):
        set_thumbnail(service, pending["long_id"], long_thumb)
        pending["long_thumb"] = True
        save_state(state)

    if not pending.get("short_id"):
        if not short_file.exists():
            short_file = render_scenes(short_scenes, folder / "render-short", True, job["category"])
            short_file.replace(folder / "short.mp4")
        make_thumbnail(short_thumb, job, True)
        _, _, short_title, short_desc = descriptions(job, pending["long_id"])
        def remember_short(video_id: str) -> None:
            pending["short_id"] = video_id
            save_state(state)
        video_id = upload_video(service, folder / "short.mp4", short_title, short_desc,
                                ["India jobs", "job alert", "India recruitment", "Shorts"],
                                on_uploaded=remember_short)
        pending["short_id"] = video_id
        save_state(state)
        log(f"Short upload created: {video_id}")
    wait_public(service, pending["short_id"])
    if not pending.get("short_thumb"):
        set_thumbnail(service, pending["short_id"], short_thumb)
        pending["short_thumb"] = True
        save_state(state)

    state["done"][key] = {
      "long_id": pending["long_id"], "short_id": pending["short_id"],
      "organisation": job["organisation"], "vacancies": job["vacancies"],
      "official_url": job["official_url"], "completed_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    }
    state["pending"] = None
    save_state(state)
    log(f"Published a complete long-form + Short pair for {job['organisation']} ({job['vacancies']:,}).")

def discover_next(state: dict) -> dict | None:
    today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    published_today = sum(
        1 for row in state["done"].values()
        if isinstance(row, dict) and row.get("completed_at", "").startswith(today_ist)
    )
    if published_today >= int(CONFIG.get("max_pairs_per_day", 4)):
        log(f"Daily safety cap reached ({published_today} completed job pairs); remaining jobs stay queued for tomorrow.")
        return None
    entries = []
    seen = set()
    # Live public listing pages are used only to locate candidate detail URLs.
    # Their titles and article text are never reused in the generated videos.
    for listing_url in CONFIG["discovery_urls"]:
        response = SESSION.get(listing_url, timeout=TIMEOUT)
        response.raise_for_status()
        page_host = (urlparse(response.url).hostname or "").lower()
        if page_host != "freejobalert.com" and not page_host.endswith(".freejobalert.com"):
            raise RuntimeError("FreeJobAlert listing redirected to an unexpected host")
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.find_all("tr"):
            for anchor in row.find_all("a", href=True):
                label = anchor.get_text(" ", strip=True).lower()
                target = urljoin(response.url, anchor["href"].strip())
                host = (urlparse(target).hostname or "").lower()
                if host != "freejobalert.com" and host != "www.freejobalert.com" and not host.endswith(".freejobalert.com"):
                    continue
                if not re.search(r"details|view|more|notification|apply|click", label):
                    continue
                if target not in seen:
                    seen.add(target)
                    entries.append({"link": target})
        # Some page variants render cards rather than table rows.
        for anchor in soup.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True).lower()
            target = urljoin(response.url, anchor["href"].strip())
            host = (urlparse(target).hostname or "").lower()
            if host != "freejobalert.com" and host != "www.freejobalert.com" and not host.endswith(".freejobalert.com"):
                continue
            if not re.search(r"get details|view details|read more", label):
                continue
            if target not in seen:
                seen.add(target)
                entries.append({"link": target})
    for entry in entries[:CONFIG["max_discovery_entries"]]:
        source_ref = entry.get("link", "")
        if not source_ref:
            continue
        discovery_key = hashlib.sha256(source_ref.encode()).hexdigest()[:24]
        if discovery_key in state["done"]:
            continue
        try:
            job, reason = candidate_job(entry)
        except Exception as exc:
            # A network or parsing error is retried on the next poll.
            log(f"Temporary verification error for a listing item: {exc}")
            continue
        if job is None:
            state["done"][discovery_key] = {
                "status": "skipped", "reason": reason,
                "checked_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"
            }
            save_state(state)
            continue
        if job["key"] in state["done"]:
            state["done"][discovery_key] = {"status": "duplicate", "job_key": job["key"]}
            save_state(state)
            continue
        job["discovery_key"] = discovery_key
        return job
    return None

def self_test() -> None:
    assert host_allowed("https://ssc.gov.in/") is True
    assert host_allowed("https://www.freejobalert.com/") is False
    assert host_allowed("http://ssc.gov.in/") is False
    assert parse_vacancies("Total number of vacancies: 1,250", "") == 1250
    assert is_india_wide("Candidates from all states may apply", "Recruitment notice", "upsc.gov.in")
    assert not is_india_wide("State-wise vacancies only. Domicile is mandatory", "Notice", "upsc.gov.in")
    assert not host_allowed("https://bihar.gov.in/recruitment/")
    assert category_for("SBI recruitment", "sbi.co.in") == "BANKS"
    assert category_for("Railway recruitment", "rrbcdg.gov.in") == "RAILWAY"
    log("Self-test passed.")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.run:
        parser.error("Use --self-test or --run")
    state = load_state()
    service = credentials()
    job = state.get("pending")
    if not job:
        job = discover_next(state)
        if not job:
            log("No new verified India-wide mass recruitment with 500+ vacancies was found.")
            return
        state["pending"] = job
        save_state(state)
    log(f"Preparing {job['organisation']} | {job['category']} | {job['vacancies']:,} vacancies")
    run_one(service, state, job)

if __name__ == "__main__":
    main()
