#!/usr/bin/env python3
"""One-time local OAuth bootstrap for the Bharat Hiring Brief channel.

The script resolves @india_jobs_1 via YouTube's official forHandle filter,
then separately verifies that the same channel is owned by the OAuth account.
Never commit the client JSON or paste the printed refresh token into chat.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
EXPECTED_HANDLE = "@india_jobs_1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, help="Google OAuth Desktop client JSON file")
    parser.add_argument("--handle", default=EXPECTED_HANDLE, help="YouTube handle to resolve exactly")
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

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # Exact public handle resolution using the official YouTube Data API.
    resolved = youtube.channels().list(
        part="id,snippet", forHandle=args.handle, maxResults=1
    ).execute().get("items", [])
    if len(resolved) != 1:
        raise SystemExit(
            f"YouTube could not resolve {args.handle!r} to exactly one channel. "
            "Check the handle and try again; no secrets were printed."
        )

    channel = resolved[0]
    channel_id = channel["id"]
    snippet = channel.get("snippet", {})
    resolved_handle = (snippet.get("customUrl") or "").casefold()
    expected = args.handle.casefold()
    if resolved_handle and resolved_handle != expected:
        raise SystemExit(
            f"YouTube resolved the handle to {resolved_handle!r}, not {expected!r}. "
            "No secrets were printed."
        )

    # Confirm OAuth is actually authorised for the resolved channel. This
    # prevents a public handle lookup alone from being treated as upload consent.
    owned = youtube.channels().list(
        part="id,snippet", mine=True, maxResults=50
    ).execute().get("items", [])
    owned_ids = {item.get("id") for item in owned}
    if channel_id not in owned_ids:
        print(f"Resolved channel: {snippet.get('title', '(untitled)')} ({channel_id})")
        print("Channels owned by the authorised Google account:")
        for item in owned:
            print(f"  - {item.get('snippet', {}).get('title', '(untitled)')} ({item.get('id')})")
        raise SystemExit(
            "\nOAuth is not authorised for the requested channel. Re-run this script "
            "and sign into/select the Google or Brand account that owns @india_jobs_1. "
            "No refresh token or secrets were printed."
        )

    print(f"\nVerified channel: {args.handle} -> {snippet.get('title', '(untitled)')} ({channel_id})")
    print("The channel was also returned by the authenticated mine=true ownership check.")
    print("Add these as GitHub Actions repository secrets. Do not commit or share them:")
    print("JOBS_YOUTUBE_CLIENT_ID=" + creds.client_id)
    print("JOBS_YOUTUBE_CLIENT_SECRET=" + flow.client_config.get("client_secret", ""))
    print("JOBS_YOUTUBE_REFRESH_TOKEN=" + creds.refresh_token)
    print("JOBS_YOUTUBE_CHANNEL_ID=" + channel_id)
    print("\nThe publisher will verify this channel ID again before making new uploads public.")
    print("Never put the client JSON or printed secrets in the repository or chat.")


if __name__ == "__main__":
    main()
