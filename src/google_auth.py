"""Google API auth for unattended container runs.

The original flow called InstalledAppFlow.run_local_server(), which opens a
browser for consent — impossible in a headless container, where it would hang
until the task timed out rather than failing. Here the token is mounted and
only ever refreshed:

    /config/google/credentials.json  (OAuth client, read-only)
    /config/google/token.json        (authorised user token, MOUNTED WRITABLE)

token.json must be writable: a refreshed access token is written back, and
losing that would mean a fresh refresh on every run. If the token is missing or
cannot be refreshed, this raises — generate a new one locally with
`python src/google_auth.py --authorise` and copy it into the mount.
"""

from __future__ import annotations

import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
]


class GoogleAuthError(Exception):
    """Raised when usable credentials cannot be obtained without a browser."""


def load_credentials() -> Credentials:
    token_path = settings.google_token_path

    if not token_path.exists():
        raise GoogleAuthError(
            f"Google token not found at {token_path}. Generate one locally with "
            "'python src/google_auth.py --authorise' and mount it there. "
            "Interactive consent cannot run in the container."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.valid:
        return creds

    if not (creds.expired and creds.refresh_token):
        raise GoogleAuthError(
            f"Google token at {token_path} is invalid and has no refresh token. "
            "Re-authorise locally and replace the mounted token.json."
        )

    try:
        creds.refresh(Request())
    except Exception as e:
        raise GoogleAuthError(
            f"Failed to refresh the Google token at {token_path}: {e}. "
            "Re-authorise locally and replace the mounted token.json."
        ) from e

    try:
        token_path.write_text(creds.to_json())
    except OSError as e:
        # Not fatal for this run, but every future run pays the refresh cost.
        print(
            f"WARNING: could not write refreshed token to {token_path} ({e}). "
            "Mount it writable so refreshes persist."
        )

    return creds


def build_auth_service(auth_type: str):
    creds = load_credentials()

    services = {
        'sheets': ('sheets', 'v4'),
        'docs': ('docs', 'v1'),
        'drive': ('drive', 'v3'),
        'admin': ('admin', 'directory_v1'),
    }
    if auth_type not in services:
        raise ValueError(f"Unknown auth_type: {auth_type}")

    name, version = services[auth_type]
    return build(name, version, credentials=creds)


def exponential_backoff(api_function, *args, **kwargs):
    max_retries = 10
    retry_delay = 1

    for _ in range(max_retries):
        try:
            return api_function(*args, **kwargs)
        except HttpError as error:
            if error.resp.status == 429:
                print(f"Rate limit exceeded. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise

    raise GoogleAuthError(f"Gave up after {max_retries} rate-limited attempts")


def _authorise_interactively() -> None:
    """Developer helper — run on a workstation, never in the container."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = settings.google_credentials_path
    token_path = settings.google_token_path

    if not creds_path.exists():
        raise GoogleAuthError(f"OAuth client file not found at {creds_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Wrote {token_path}. Mount this file into the container (writable).")


if __name__ == '__main__':
    if '--authorise' in sys.argv or '--authorize' in sys.argv:
        _authorise_interactively()
    else:
        load_credentials()
        print("Mounted Google credentials are valid.")
