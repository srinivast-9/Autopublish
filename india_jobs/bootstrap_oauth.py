#!/usr/bin/env python3
"""One-time local OAuth bootstrap for the Bharat Hiring Brief YouTube channel.

Run on a trusted local computer. Never commit the downloaded Google client JSON
or paste the printed refresh token into chat.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, help="Google OAuth Desktop client JSON file")
    args = parser.parse_args()
    path = Path(args.client_secrets).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"OAuth client file not found: {path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), scopes=SCOPES)
    creds = flow.run_local_server(
        host="localhost", port=0, open_browser=False,
        access_type="offline", prompt="consent",
    )
    if not creds.refresh_token:
        raise SystemExit("Google did not issue a refresh token. Revoke app access and run again.")
    print("\nAdd these as GitHub Actions repository secrets; do not commit or share them:")
    print("JOBS_YOUTUBE_CLIENT_ID=" + creds.client_id)
    print("JOBS_YOUTUBE_CLIENT_SECRET=" + flow.client_config.get("client_secret", ""))
    print("JOBS_YOUTUBE_REFRESH_TOKEN=" + creds.refresh_token)
    print("\nAlso add JOBS_YOUTUBE_CHANNEL_ID with the exact channel ID of the new channel.")
    print("Choose the Google/Brand account that owns the new channel during consent.")

if __name__ == "__main__":
    main()
