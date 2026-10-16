# Chess Bits — free daily publisher

The default-branch workflow `.github/workflows/chess-bits-daily.yml` is the single publishing path. It tries at **5:00 PM India time**, then retries **hourly** if publication has not succeeded. A committed ledger and per-video marker prevent a retry from intentionally uploading a second copy of a successful video. Oldest missed dates are caught up first.

## What it does

1. Alternates between 9:16 tactical-puzzle Shorts and 16:9 long-form lessons. Long-form lessons rotate through openings and gambits, with a tactics-focused lesson after every two long-form opening lessons.
2. Requires legal moves, a complete verified solution and a checked final position. Puzzle Shorts are checkmate-only: mate in one, mate in two, or mate in three (at most five plies), with only one selected solution line discussed.
3. Tracks used puzzle IDs, a normalized starting-position fingerprint and a position-plus-solution fingerprint. This rejects a repeated board position even if a source lists a different solution, and avoids recently used tactical themes when another valid candidate exists.
4. Generates narration with the free `edge-tts` package; no paid TTS subscription is used. Long-form voiceover is split into move-specific narration clips; each piece moves in a quick ~0.45–0.72 second tween when that move is spoken, then the resulting position holds while its explanation finishes.
5. Reuses the approved Chess Bits Neo-piece visual renderer, checks MP4 streams, dimensions, duration and a full FFmpeg decode, and refuses to publish on a QA failure. Puzzle Shorts preserve the start position during the thinking phase and then reveal and narrate one solution move at a time, with each movement aligned to its spoken cue.
6. Uses background music **only for puzzle Shorts**. Long-form videos have no background music. Puzzle source-provider names are omitted from voiceover, on-screen text, title, puzzle description and tags. Where a music track requires attribution, its credit remains in the YouTube description.
7. Includes original teaching explanations and further-study references to the public-domain book `Technique of Modern Tactics` (1919) in tactics-focused long-form lessons. It does not reproduce book passages.
8. Uploads through the official YouTube Data API, verifies the intended Chess Bits channel and public visibility, and commits the ledger. Success emails are disabled; the workflow emails only when a due upload fails, provided SMTP secrets are configured.
9. Retries hourly after failure. A confirmed public upload is not re-uploaded just because a state commit or email step failed.

The GitHub repository is public, so standard GitHub-hosted Actions runners are free under GitHub's current billing policy. This workflow does not require a paid Render service, Metricool plan, or subscription-based extension. The legacy Render worker branch is not used by this workflow.

## One-time setup required

Automatic publishing cannot start until the channel authorizes an unattended uploader. This is a one-time setup, not a daily approval.

### 1. Set up the free YouTube API client

1. Open [Google Cloud Console](https://console.cloud.google.com/), create or select a project, and enable **YouTube Data API v3**.
2. Configure OAuth consent, then create an OAuth client of type **Desktop app** and download its client JSON file.
3. Run this locally on your own computer (do not upload the downloaded JSON to this repository):

   ```bash
   python -m pip install google-auth-oauthlib
   python scripts/create_youtube_refresh_token.py --client-secrets /path/to/client_secret.json
   ```

4. Sign in to the Google account that owns the **Chess Bits** YouTube channel and approve the requested read/upload permissions.
5. The script requests only upload and read access. Existing videos are never deleted, edited, or made public by the recovery path. The script prints three values. Add them under GitHub repository **Settings → Secrets and variables → Actions → New repository secret**:
   - `YOUTUBE_CLIENT_ID`
   - `YOUTUBE_CLIENT_SECRET`
   - `YOUTUBE_REFRESH_TOKEN`

Never put these values in source files, workflow YAML, issues, or chat. If the refresh token is revoked, rerun the local setup and replace the secret.

**Important YouTube restriction:** Google currently restricts uploads from unverified YouTube API projects created after July 28, 2020 to private viewing until the project passes its YouTube API compliance audit. Moving OAuth consent to Production prevents the seven-day Testing-token expiry; it does **not** replace the separate YouTube API compliance audit required for public uploads. See [Google OAuth token lifetime](https://developers.google.com/identity/protocols/oauth2/) and [YouTube API upload policy](https://developers.google.com/youtube/v3/docs/videos/). The workflow checks public visibility and will report failure rather than claiming that a private upload is public. This audit is free but is external to this repository; code cannot bypass it.

## Puzzle and tactics content rules

- A puzzle Short uses neutral challenge wording only: no source-provider mentions in narration, graphics, title, description or tags. Any required music license credit remains in the description only.
- Select checkmate puzzles only: mate in one, two or three, with a legal main line of 1, 3 or 5 plies ending in verified checkmate. Reject longer lines, malformed positions and repeat positions; prefer high-difficulty candidates and avoid recently used tactical themes when valid alternatives exist.
- Long-form lesson selection inserts a tactical-combination lesson after every two long-form opening lessons. Topics include deflection, pins, interference, batteries, sacrifices, removing defenders and mating attacks, with original explanations and a public-domain further-study reference.
- Animation uses short move tweens tied to each spoken move cue, then holds the resulting board while its explanation continues. The final-position/checkmate label is not allowed to appear before the last move animation completes.

### 2. Failure-only email notifications

To receive an email **only when a due upload fails**, add these repository Actions secrets:

- `CHESSBITS_NOTIFY_EMAIL`: destination address.
- `SMTP_HOST`: mail server (for example, `smtp.gmail.com` or `smtp.mail.yahoo.com`).
- `SMTP_PORT`: normally `465` for SSL or `587` for STARTTLS.
- `SMTP_USERNAME`: sender email address.
- `SMTP_APP_PASSWORD`: an app-specific password from that mail provider.

These mail secrets are required for email alerts. Without them, publishing still runs, but failures can only be inspected in GitHub Actions. Do not use your normal email account password if the provider supports app-specific passwords.

## Timing and recovery

- Primary attempt: daily at 5:00 PM IST.
- Workflow checks run every hour around the clock. A new day's normal upload is gated until 5:00 PM IST, but any older missed date keeps retrying hourly.
- Hourly retries do not publish an extra video once the current day's upload is confirmed public.
- Only one publisher job can run at a time. Failed dates remain due and are retried; the next successful upload advances the ledger. Same-day additional uploads do not shift the next day's alternating content type.
- The workflow is also available under **GitHub → Actions → Chess Bits Daily Auto Publisher → Run workflow** for an initial manual test.

No software system can guarantee delivery during an external provider outage, a revoked credential, quota rejection, or GitHub incident. The intended behavior is automatic retry and a clear alert, not silent success. Do not treat the pipeline as production-ready until the first full run completes and its public YouTube URL is verified.

## Safety

- It only uploads to the channel ID configured in `scripts/chessbits_daily.py`; it refuses to publish if OAuth points elsewhere.
- It does not delete, edit, or make existing YouTube videos private.
- It does not publish a video until notation checks, audio checks, resolution/duration checks and full media decoding pass.
- The ledger lives in `state/published.json`; it contains public video IDs/URLs and content IDs, not credentials.
