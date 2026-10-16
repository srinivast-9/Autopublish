# Chess Bits — free daily publisher

The default-branch workflow `.github/workflows/chess-bits-daily.yml` is the one publishing path. It runs at **5:00 PM India time**, then makes automatic recovery attempts later the same evening and overnight. A committed ledger and per-video marker prevent a retry from intentionally uploading a second copy of a successful video. Oldest missed dates are caught up first.

## What it does

1. Alternates between 9:16 tactical-puzzle Shorts and 16:9 long-form lessons. Long-form lessons rotate through openings and gambits, with a tactics-focused lesson after every two long-form opening lessons.
2. Requires legal move sequences, a complete verified solution and a checked final position. Puzzle selection rotates between a curated bank of classic tactical combinations and a high-difficulty public puzzle feed. Feed puzzles must be rated at least 2000 and contain a multi-ply forcing line.
3. Tracks used puzzle IDs, a normalized starting-position fingerprint and a position-plus-solution fingerprint. This rejects a repeated board position even if a source lists a different solution, and avoids recently used tactical themes when another valid candidate exists.
4. Generates narration with the free `edge-tts` package; no paid TTS subscription is used. Long-form voiceover is split into move-specific narration clips; each piece moves in a quick ~0.45–0.72 second tween when that move is spoken, then the resulting position holds while its explanation finishes.
5. Reuses the approved Chess Bits Neo-piece visual renderer, checks MP4 streams, dimensions, duration and a full FFmpeg decode, and refuses to publish on a QA failure. Puzzle Shorts preserve the start position during the thinking phase and then reveal and narrate one solution move at a time, with each movement aligned to its spoken cue.
6. Uses background music **only for puzzle Shorts**. Long-form videos have no background music. Puzzle source-provider names are omitted from voiceover, on-screen text, title, puzzle description and tags. Where a music track requires attribution, its credit remains in the YouTube description.
7. Includes original teaching explanations and further-study references to the public-domain book `Technique of Modern Tactics` (1919) in tactics-focused long-form lessons. It does not reproduce book passages.
6. Uploads through the official YouTube Data API, verifies that the intended Chess Bits channel owns the video and that the upload is public, commits the ledger, and emails the result if SMTP is configured.
7. Retries automatically through scheduled recovery runs. A confirmed public upload is not re-uploaded just because the state commit or email step failed.

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
- Prefer hard, forcing multi-move positions (current public-feed filter: rating 2000+, at least four solution plies), verify legality and the final position, track puzzle fingerprints, and reject repeated or malformed lines. Curated classic combinations provide an additional puzzle pool.
- Long-form lesson selection inserts a tactical-combination lesson after every two long-form opening lessons. Topics include deflection, pins, interference, batteries, sacrifices, removing defenders and mating attacks, with original explanations and a public-domain further-study reference.
- Animation uses short move tweens tied to each spoken move cue, then holds the resulting board while its explanation continues. The final-position/checkmate label is not allowed to appear before the last move animation completes.

### 2. Optional email notifications

To receive one email for each verified upload and an alert after a failed run, add these repository Actions secrets:

- `CHESSBITS_NOTIFY_EMAIL`: destination address.
- `SMTP_HOST`: mail server (for example, `smtp.gmail.com` or `smtp.mail.yahoo.com`).
- `SMTP_PORT`: normally `465` for SSL or `587` for STARTTLS.
- `SMTP_USERNAME`: sender email address.
- `SMTP_APP_PASSWORD`: an app-specific password from that mail provider.

Email is optional; if these secrets are absent, publishing still runs and run results remain in GitHub Actions. Do not use your normal email account password if the provider supports app-specific passwords.

## Timing and recovery

- Primary attempt: daily at 5:00 PM IST.
- Recovery attempts: 6:30 PM, 8:30 PM, 10:30 PM, 12:30 AM and 2:30 AM IST.
- Overnight retries may catch up an earlier missed calendar date immediately, but do not publish a new day's normal slot before 5:00 PM IST.
- Only one publisher job can run at a time. Failed dates remain due and are retried; the next successful upload advances the ledger. Same-day additional uploads do not shift the next day's alternating content type.
- The workflow is also available under **GitHub → Actions → Chess Bits Daily Auto Publisher → Run workflow** for an initial manual test.

No software system can guarantee delivery during an external provider outage, a revoked credential, quota rejection, or GitHub incident. The intended behavior is automatic retry and a clear alert, not silent success. Do not treat the pipeline as production-ready until the first full run completes and its public YouTube URL is verified.

## Safety

- It only uploads to the channel ID configured in `scripts/chessbits_daily.py`; it refuses to publish if OAuth points elsewhere.
- It does not delete, edit, or make existing YouTube videos private.
- It does not publish a video until notation checks, audio checks, resolution/duration checks and full media decoding pass.
- The ledger lives in `state/published.json`; it contains public video IDs/URLs and content IDs, not credentials.
