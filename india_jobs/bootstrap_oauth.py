#!/usr/bin/env python3
"""One-time local OAuth bootstrap for the Bharat Hiring Brief channel.

Run on a trusted local computer. The script looks up the authorised YouTube
channels and automatically matches @india_jobs_1 to YouTube's permanent ID.
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


def normalise_handle(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("https://www.youtube.com/"):
        value = value.rsplit("/", 1)[-1]
    if not value.startswith("@"):
        value = "@" + value
    return value.rstrip("/").casefold()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, help="Google OAuth Desktop client JSON file")
    parser.add_argument("--handle", default=EXPECTED_HANDLE, help="YouTube handle to match exactly")
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
    response = youtube.channels().list(
        part="id,snippet", mine=True, maxResults=50
    ).execute()
    channels = response.get("items", [])
    if not channels:
        raise SystemExit(
            "No YouTube channel was returned for the authorised account. "
            "Re-run OAuth and select the Google/Brand account that owns @india_jobs_1."
        )

    wanted = normalise_handle(args.handle)
    matches = []
    for channel in channels:
        snippet = channel.get("snippet", {})
        custom_url = normalise_handle(snippet.get("customUrl", ""))
        if custom_url == wanted:
            matches.append(channel)

    if len(matches) != 1:
        print("\nYouTube did not return one exact handle match for", wanted)
        print("Channels visible to the authorised Google account:")
        for channel in channels:
            snippet = channel.get("snippet", {})
            print(
                f"  - {snippet.get('title', '(untitled)')} | "
                f"{snippet.get('customUrl', '(no handle)')} | "
                f"{channel.get('id', '(no ID)')}"
            )
        raise SystemExit(
            "\nNo secrets were printed. Sign in with the Google/Brand account "
            "that owns the requested channel and rerun this script. Do not choose "
            "a similarly named channel."
        )

    channel_id = matches[0]["id"]
    channel_title = matches[0].get("snippet", {}).get("title", "")
    print(f"\nExact handle match: {wanted} -> {channel_title} ({channel_id})")
    print("Add these as GitHub Actions repository secrets. Do not commit or share them:")
    print("JOBS_YOUTUBE_CLIENT_ID=" + creds.client_id)
    print("JOBS_YOUTUBE_CLIENT_SECRET=" + flow.client_config.get("client_secret", ""))
    print("JOBS_YOUTUBE_REFRESH_TOKEN=" + creds.refresh_token)
    print("JOBS_YOUTUBE_CHANNEL_ID=" + channel_id)
    print("\nThe publisher will check this channel ID before making new uploads public.")
    print("Never put the client JSON or printed secrets in the repository or chat.")


if __name__ == "__main__":
    main()
