# Chess Bits cloud render worker

An authenticated FastAPI service that moves Runway narration download and chess-video rendering into Render's cloud runtime. It does not publish to YouTube directly; after successful QA, the existing Metricool publishing flow can import the returned signed HTTPS video URL. No secrets are stored in this repository.

## Endpoints

- `GET /health`: runtime readiness without exposing secrets.
- `POST /v1/jobs/render`: authenticated; accepts a legal PGN, `video_type` (`puzzle_short` or `longform`), one or more `voiceover_urls`, title, and optional `music_url`.
- `GET /v1/jobs/{job_id}`: authenticated status polling. A completed result includes a signed `media_url`, hash, byte count, duration, dimensions, mate flag, ply count, and music flag.
- `GET /media/{job_id}.mp4?expires=...&sig=...`: time-limited signed URL intended for Metricool to fetch the MP4.

The Docker build fetches the approved Chess.com Neo piece sprites from the Chess.com asset CDN. The service keeps completed files on ephemeral disk, so Metricool must import the URL shortly after completion. This first deployment is a handoff-replacement test worker, not yet a durable queue. It never deletes or modifies YouTube content.

## Required Render environment variables

- `CHESSBITS_API_TOKEN`: high-entropy Bearer token for job/status endpoints.
- `MEDIA_SIGNING_SECRET`: separate high-entropy secret used to sign time-limited video URLs.
- `PUBLIC_BASE_URL`: canonical HTTPS URL for this service (for example, `https://chess-bits-cloud-worker.onrender.com`).
- Optional: `MEDIA_TTL_SECONDS` (600–21600, default six hours), `CHESSBITS_DATA_DIR` (default `/tmp/chessbits-worker`), and `LOG_LEVEL`.

Never commit credentials, Runway signed URLs, OAuth tokens, or API keys. Store secrets only in the Render Dashboard or another secret store. The repository contains no credentials.

## Request example

```json
{
  "title": "A forcing mate",
  "video_type": "puzzle_short",
  "require_checkmate": true,
  "pgn": "[Event \"Mate test\"]\n[Result \"1-0\"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0",
  "voiceover_urls": ["https://<allowed-runway-cdn-host>/<signed-audio-path>"],
  "music_url": "https://<allowed-music-cdn-host>/<track-path>"
}
```

The request example is illustrative only. Always supply an independently verified PGN. A `puzzle_short` is rejected unless the final position is checkmate. The publishing flow must also require `music_included=true` when a separate track is required.

## Safety and reliability

- Downloads are HTTPS-only and restricted to Runway/CloudFront and listed music providers; redirects are revalidated.
- Partial downloads are discarded and audio is decoded with FFmpeg before rendering.
- Every PGN move is checked for legality; mate shorts require a terminal checkmate.
- The output audio/video streams, duration, full decode, SHA-256 and format dimensions are checked.
- Input size, duration and ply count are capped. The initial worker stores job state in memory and output files on ephemeral disk; durable queue/object storage is a later hardening step.
- If music is omitted, output includes a warning and `music_included=false`; publishing should be blocked if separate music is a requirement.
