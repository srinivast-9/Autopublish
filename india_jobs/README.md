# Bharat Hiring Brief — free India-wide recruitment publisher

This is an independent pipeline in the existing Autopublish repository. It does not modify the Chess Bits workflow or its state ledger.

## Rules applied

- FreeJobAlert's Latest Notifications and New Updates listing pages are used only to discover candidate notices; an RSS endpoint is not assumed. The workflow does not publish FreeJobAlert article text, artwork, URLs, descriptions, layout, or branding.
- Each candidate must have a direct HTTPS link on an approved recruiting-organisation domain. Official government domains ending in `.gov.in` / `.nic.in` and a curated list of bank/PSU/railway domains are accepted.
- The official source text/PDF must establish a nationwide scope (or be hosted by a recognised national recruiter without a state-only restriction).
- The notice must disclose at least 500 vacancies. State-only, unverified, expired, image-only/unreadable or insufficiently structured notices are skipped.
- The videos are written from fields extracted from the official notice, with original candidate checklists and application-safety guidance. No source-site copy is used.
- Every description points only to the recruiting organisation's official notice/application page. The Short is uploaded after the long video and links to that full video.
- A state ledger prevents completed job pairs from being repeated and preserves partial upload IDs so an interrupted Short does not cause the long video to be uploaded again.

## Free stack

GitHub Actions (this repository is public), Python, Requests, Feedparser, BeautifulSoup, PyMuPDF, Pillow, FFmpeg, Edge-TTS, and the official YouTube Data API. No paid LLM, voice, thumbnail, video-rendering, scheduler, or hosting service is used.

The workflow polls every 30 minutes (at minutes 17 and 47). GitHub scheduled runs are best-effort and can be delayed or dropped during service load; this is not an instant webhook. A failed attempt remains eligible for the next poll.

## One-time channel setup

1. Create the new YouTube channel and choose its name/artwork. The provisional in-video brand is **Bharat Hiring Brief**.
2. Use a Google OAuth Desktop client that has YouTube Data API v3 enabled. You may reuse an existing OAuth client, but create a fresh refresh token while signed into the Google/Brand account that owns this channel.
3. On a trusted computer, install the requirements and run:

   ```bash
   python -m pip install -r india_jobs/requirements.txt
   python india_jobs/bootstrap_oauth.py --client-secrets /path/to/client_secret.json
   ```

4. Add these GitHub repository Actions secrets:
   - `JOBS_YOUTUBE_CLIENT_ID`
   - `JOBS_YOUTUBE_CLIENT_SECRET`
   - `JOBS_YOUTUBE_REFRESH_TOKEN`
   - `JOBS_YOUTUBE_CHANNEL_ID`

   The channel ID is visible in YouTube Studio → Settings → Channel → Advanced settings. Never put secrets in source files or chat. The workflow checks channel ownership before every upload.

5. Once those four secrets are present, the scheduled publisher starts automatically. It checks the authorised channel ID before every upload and refuses to upload to a different channel.

## Content and monetization note

Automation does not guarantee YouTube Partner Program acceptance. YouTube explicitly warns that repetitive, template-like or mass-produced videos can be ineligible for monetization. This pipeline adds independently written eligibility guidance, a candidate checklist, source verification and application-safety commentary, but the owner remains responsible for checking the channel's actual originality and policy compliance.

## Safety

- No video is posted if a direct official recruiting source cannot be verified.
- No state-specific job is intended to pass the nationwide filter.
- No vacancy figure, deadline, qualification, age limit, pay or selection stage is invented. Missing fields are explicitly sent to the official notice.
- No FreeJobAlert link appears in video titles, descriptions, narration or thumbnails.
- No existing YouTube video is deleted, edited or made private.
