"""Download file attachment from a GitHub issue body.

CLI usage (called by upload.yml):
    python -m engine.download_attachment

Reads env:
    GITHUB_TOKEN  — for authenticated downloads
    ISSUE_BODY    — raw markdown body of the issue

Writes downloaded file to /tmp/upload/{original_filename}.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

# GitHub attachment URL patterns
ATTACHMENT_PATTERNS = [
    # New format: https://github.com/user-attachments/assets/{uuid}/{filename}
    r'https://github\.com/user-attachments/assets/[a-f0-9\-]+/[^\s\)]+',
    # Older format: https://github.com/{owner}/{repo}/files/{id}/{filename}
    r'https://github\.com/[^/]+/[^/]+/files/\d+/[^\s\)]+',
    # Generic markdown image/link with github in URL
    r'https://github\.com/[^\s\)\]]+',
]

UPLOAD_DIR = Path("/tmp/upload")


def extract_attachment_url(body: str) -> str | None:
    """Extract the first file attachment URL from issue body markdown."""
    for pattern in ATTACHMENT_PATTERNS:
        match = re.search(pattern, body)
        if match:
            url = match.group(0).rstrip(")")
            return url
    return None


def guess_filename(url: str) -> str:
    """Extract filename from URL path."""
    parsed = urlparse(url)
    path_parts = parsed.path.rstrip("/").split("/")
    name = unquote(path_parts[-1]) if path_parts else "unknown_file"
    # Strip any trailing markdown artifacts
    name = name.split(")")[0].split("]")[0]
    return name


def download_file(url: str, token: str) -> Path:
    """Download a file from URL to /tmp/upload/."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = guess_filename(url)
    dest = UPLOAD_DIR / filename

    headers = {}
    if "github.com" in url:
        headers["Authorization"] = f"Bearer {token}"

    print(f"Downloading {url} → {dest}")
    resp = requests.get(url, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            f.write(chunk)

    print(f"  → {dest.stat().st_size} bytes saved")
    return dest


def main() -> None:
    """CLI entry point."""
    body = os.environ.get("ISSUE_BODY", "")
    token = os.environ.get("GITHUB_TOKEN", "")

    if not body:
        print("ERROR: ISSUE_BODY is empty")
        sys.exit(1)

    url = extract_attachment_url(body)
    if not url:
        print("ERROR: No attachment URL found in issue body")
        print(f"  Body preview: {body[:200]}")
        sys.exit(1)

    download_file(url, token)
    print("Download complete.")


if __name__ == "__main__":
    main()
