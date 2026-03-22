"""Thin wrapper around GitHub's repository_dispatch API."""

from __future__ import annotations

import json

import requests


def send_dispatch(
    token: str,
    repo: str,
    event_type: str,
    payload: dict,
) -> bool:
    """Send a repository_dispatch event.

    Args:
        token: GitHub PAT with repo scope.
        repo: Target repo in "owner/name" format.
        event_type: The dispatch event type string.
        payload: The client_payload dict (must be < 65 KB serialized).

    Returns:
        True if dispatch was accepted (HTTP 204).
    """
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {
        "event_type": event_type,
        "client_payload": payload,
    }

    serialized = json.dumps(body)
    if len(serialized.encode()) > 65_000:
        print(f"WARNING: Payload to {repo} is {len(serialized.encode())} bytes (limit ~65 KB)")

    resp = requests.post(url, headers=headers, json=body, timeout=30)

    if resp.status_code == 204:
        print(f"  Dispatch OK → {repo} [{event_type}]")
        return True

    print(f"  Dispatch FAILED → {repo} [{event_type}] HTTP {resp.status_code}: {resp.text}")
    return False


def send_dispatch_batch(
    token: str,
    dispatches: list[tuple[str, str, dict]],
) -> dict[str, bool]:
    """Send multiple dispatches sequentially.

    Args:
        dispatches: List of (repo, event_type, payload) tuples.

    Returns:
        Dict mapping "repo:event_type" to success bool.
    """
    results = {}
    for repo, event_type, payload in dispatches:
        key = f"{repo}:{event_type}"
        results[key] = send_dispatch(token, repo, event_type, payload)
    return results
