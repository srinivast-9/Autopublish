#!/usr/bin/env python3
"""One-time local OAuth bootstrap for Chess Bits YouTube uploads.

Run this on your own computer, not in GitHub Actions. Do not commit the JSON
client file or paste refresh tokens into chat.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, help="Path to Google OAuth Desktop client JSON")
    args = parser.parse_args()
    path = Path(args.client_secrets).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"OAuth client JSON was not found: {path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), scopes=SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise SystemExit("Google did not return a refresh token. Revoke this app's access and rerun with consent.")
    client_id = credentials.client_id
    # The client secret is read only from the JSON downloaded from Google Cloud.
    client_secret = flow.client_config.get("client_secret", "")
    print("\nOAuth completed. Add these as GitHub Actions repository secrets.")
    print("Do NOT commit this output, send it in chat, or store it in source code.")
    print("\nYOUTUBE_CLIENT_ID=" + client_id)
    print("YOUTUBE_CLIENT_SECRET=" + client_secret)
    print("YOUTUBE_REFRESH_TOKEN=" + credentials.refresh_token)
    print("\nThe YouTube API project must be audited by Google for public uploads if Google's current policy applies.")
    print("GitHub repository settings: Settings > Secrets and variables > Actions > New repository secret.")


if __name__ == "__main__":
    main()
