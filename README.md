# Chess Bits — free daily publisher

The default-branch workflow `.github/workflows/chess-bits-daily.yml` is the one publishing path. It runs at **5:00 PM India time**, then makes automatic recovery attempts later the same evening and overnight. A committed ledger and per-video marker prevent a retry from intentionally uploading a second copy of a successful video. Oldest missed dates are caught up first.

## What it does

1. Alternates between a 16:9 narrated opening lesson and a 9:16 tactical-puzzle Short.
2. Validates chess notation and puzzle solution moves with python-chess.
3. Generates narration with the free `edge-tts` package; no paid TTS subscription is used.
4. Reuses the approved Chess Bits Neo-piece visual renderer, checks MP4 streams, dimensions, duration and a full FFmpeg decode, and refuses to publish on a QA failure.
5. Uses background music **only for puzzle Shorts**. Long-form narrated opening videos have no background music. Shorts use a rotating selection of NCS tracks and include the required attribution in the video description.
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
5. The script prints three values. Add them under GitHub repository **Settings → Secrets and variables → Actions → New repository secret**:
   - `YOUTUBE_CLIENT_ID`
   - `YOUTUBE_CLIENT_SECRET`
   - `YOUTUBE_REFRESH_TOKEN`

Never put these values in source files, workflow YAML, issues, or chat. If the refresh token is revoked, rerun the local setup and replace the secret.

**Important YouTube restriction:** Google currently restricts uploads from unverified YouTube API projects to private viewing until the project passes its YouTube API compliance audit. Submit and complete that audit in Google's developer console/process before expecting public daily videos. The workflow checks public visibility and will report failure rather than claiming that a private upload is public. This audit is free but is external to this repository; code cannot bypass it.

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
- Only one publisher job can run at a time. Failed dates remain due and are retried; the next successful upload advances the ledger.
- The workflow is also available under **GitHub → Actions → Chess Bits Daily Auto Publisher → Run workflow** for an initial manual test.

No software system can guarantee delivery during an external provider outage, a revoked credential, quota rejection, or GitHub incident. The intended behavior is automatic retry and a clear alert, not silent success. Do not treat the pipeline as production-ready until the first full run completes and its public YouTube URL is verified.

## Safety

- It only uploads to the channel ID configured in `scripts/chessbits_daily.py`; it refuses to publish if OAuth points elsewhere.
- It does not delete, edit, or make existing YouTube videos private.
- It does not publish a video until notation checks, audio checks, resolution/duration checks and full media decoding pass.
- The ledger lives in `state/published.json`; it contains public video IDs/URLs and content IDs, not credentials.
