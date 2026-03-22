"""Clean up expired files and completed transfers.

CLI usage (called by cleanup.yml):
    python -m engine.cleanup

Reads env:
    GITHUB_TOKEN — for dispatching prune-file to peers
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from engine import config
from engine.dispatch import send_dispatch


def cleanup_expired_files(token: str) -> int:
    """Delete file indexes past their expires_at and dispatch prune to peers.

    Returns count of files cleaned up.
    """
    now = datetime.now(timezone.utc)
    cleaned = 0

    for index_file in config.FILES_DIR.glob("*.json"):
        data = config.load_json(index_file)
        expires_at = data.get("expires_at", "")
        if not expires_at:
            continue

        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            continue

        if now < expiry:
            continue

        filename = data.get("filename", index_file.stem)
        print(f"  Expired: {filename} (expired {expires_at})")

        # Collect all peers holding chunks of this file
        peers_to_notify = set()
        for chunk_info in data.get("chunks", {}).values():
            for peer in chunk_info.get("peers", []):
                peers_to_notify.add(peer)

        # Dispatch prune-file to each peer
        for peer_repo in peers_to_notify:
            send_dispatch(token, peer_repo, "prune-file", {"filename": filename})

        # Delete the file index
        index_file.unlink()
        cleaned += 1

    return cleaned


def cleanup_completed_transfers() -> int:
    """Remove transfer state files and chunk directories for completed/failed transfers.

    Returns count of transfers cleaned up.
    """
    cleaned = 0

    for transfer_file in config.TRANSFERS_DIR.glob("t_*.json"):
        data = config.load_json(transfer_file)
        status = data.get("status", "")

        if status not in ("complete", "failed", "timeout"):
            continue

        transfer_id = data.get("transfer_id", transfer_file.stem)
        print(f"  Cleanup transfer: {transfer_id} ({status})")

        # Remove chunk directory if it exists
        chunks_dir = config.TRANSFERS_DIR / transfer_id
        if chunks_dir.is_dir():
            shutil.rmtree(chunks_dir)

        # Remove transfer state file
        transfer_file.unlink()
        cleaned += 1

    return cleaned


def cleanup_stale_transfers(max_age_hours: int = 24) -> int:
    """Remove in_progress transfers that are older than max_age_hours (stuck/timed out).

    Returns count of transfers cleaned up.
    """
    now = datetime.now(timezone.utc)
    cleaned = 0

    for transfer_file in config.TRANSFERS_DIR.glob("t_*.json"):
        data = config.load_json(transfer_file)
        if data.get("status") != "in_progress":
            continue

        started_at = data.get("started_at", "")
        if not started_at:
            continue

        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            continue

        age_hours = (now - started).total_seconds() / 3600
        if age_hours < max_age_hours:
            continue

        transfer_id = data.get("transfer_id", transfer_file.stem)
        print(f"  Stale transfer: {transfer_id} ({age_hours:.1f}h old)")

        # Remove chunk directory
        chunks_dir = config.TRANSFERS_DIR / transfer_id
        if chunks_dir.is_dir():
            shutil.rmtree(chunks_dir)

        # Mark as timeout and remove
        transfer_file.unlink()
        cleaned += 1

    return cleaned


def main() -> None:
    """CLI entry point."""
    token = os.environ.get("GITHUB_TOKEN", "")

    print("Cleaning up expired files...")
    expired = cleanup_expired_files(token)
    print(f"  → {expired} expired files removed")

    print("Cleaning up completed transfers...")
    completed = cleanup_completed_transfers()
    print(f"  → {completed} completed transfers removed")

    print("Cleaning up stale transfers...")
    stale = cleanup_stale_transfers()
    print(f"  → {stale} stale transfers removed")

    # Update stats
    stats = config.load_json(config.STATS_FILE)
    file_count = len(list(config.FILES_DIR.glob("*.json")))
    active_transfers = len(list(config.TRANSFERS_DIR.glob("t_*.json")))
    stats["active_transfers"] = active_transfers
    config.save_json(config.STATS_FILE, stats)

    print(f"Done. {file_count} files, {active_transfers} active transfers remaining.")


if __name__ == "__main__":
    main()
