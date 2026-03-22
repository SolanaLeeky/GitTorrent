"""Security checks: upload authorization, peer blacklist, rate limiting, replay prevention.

Used by upload.yml and collector.py to enforce access control.
"""

from __future__ import annotations

from datetime import datetime, timezone

from engine import config


def is_upload_authorized(username: str) -> bool:
    """Check if a user is allowed to upload files.

    Returns True if:
      - allow_public_uploads is true in config, OR
      - username is in authorized_uploaders list
    """
    cfg = config.load_json(config.CONFIG_FILE)

    if cfg.get("allow_public_uploads", True):
        return True

    allowed = cfg.get("authorized_uploaders", [])
    if not allowed:
        return True  # empty list = no restriction

    return username in allowed


def is_peer_blacklisted(peer_repo: str) -> bool:
    """Check if a peer is on the blacklist."""
    cfg = config.load_json(config.CONFIG_FILE)
    return peer_repo in cfg.get("blacklisted_peers", [])


def blacklist_peer(peer_repo: str, reason: str = "") -> None:
    """Add a peer to the blacklist."""
    cfg = config.load_json(config.CONFIG_FILE)
    bl = cfg.setdefault("blacklisted_peers", [])
    if peer_repo not in bl:
        bl.append(peer_repo)
        config.save_json(config.CONFIG_FILE, cfg)
        print(f"  BLACKLISTED peer {peer_repo}: {reason}")


def check_file_size(size_bytes: int) -> bool:
    """Check if file is within the allowed size limit."""
    cfg = config.load_json(config.CONFIG_FILE)
    max_mb = cfg.get("max_file_size_mb", 100)
    return size_bytes <= max_mb * 1024 * 1024


def is_transfer_id_used(transfer_id: str) -> bool:
    """Check if a transfer ID has already been processed (replay prevention).

    Scans completed/failed transfers for duplicates.
    """
    for tf in config.TRANSFERS_DIR.glob("t_*.json"):
        data = config.load_json(tf)
        if data.get("transfer_id") == transfer_id and data.get("status") in ("complete", "failed"):
            return True
    return False


def check_rate_limit() -> bool:
    """Check if we're within the dispatch rate limit.

    Returns True if dispatches are allowed.
    """
    stats = config.load_json(config.STATS_FILE)
    cfg = config.load_json(config.CONFIG_FILE)

    limit = cfg.get("rate_limit_dispatches_per_hour", 4000)
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    hourly = stats.get("hourly_dispatches", {})
    count = hourly.get(current_hour, 0)

    return count < limit


def record_dispatch() -> None:
    """Record a dispatch for rate limiting."""
    stats = config.load_json(config.STATS_FILE)
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    hourly = stats.setdefault("hourly_dispatches", {})

    # Clean old hours (keep only last 2)
    keys = sorted(hourly.keys())
    for k in keys[:-2]:
        del hourly[k]

    hourly[current_hour] = hourly.get(current_hour, 0) + 1
    config.save_json(config.STATS_FILE, stats)


def track_peer_failure(peer_repo: str) -> None:
    """Track a chunk verification failure for a peer. Auto-blacklist after threshold."""
    peers_data = config.load_json(config.PEERS_FILE)
    peer_info = peers_data.get("peers", {}).get(peer_repo, {})

    failed = peer_info.get("failed_fetches", 0) + 1
    peer_info["failed_fetches"] = failed
    peers_data.setdefault("peers", {})[peer_repo] = peer_info
    config.save_json(config.PEERS_FILE, peers_data)

    cfg = config.load_json(config.CONFIG_FILE)
    threshold = cfg.get("max_failed_chunks_before_blacklist", 5)

    if failed >= threshold:
        blacklist_peer(peer_repo, f"{failed} failed chunk verifications")
