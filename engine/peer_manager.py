"""Peer health checks, registration, and rebalancing.

CLI usage (called by tracker workflows):
    python -m engine.peer_manager --action=health
    python -m engine.peer_manager --action=rebalance
    python -m engine.peer_manager --action=register   --peer=owner/repo
    python -m engine.peer_manager --action=deregister --peer=owner/repo
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from engine import config
from engine.dispatch import send_dispatch
from engine.models import PeerInfo


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_str: str) -> float:
    """Hours elapsed since an ISO timestamp."""
    if not iso_str:
        return float("inf")
    then = datetime.fromisoformat(iso_str)
    now = datetime.now(timezone.utc)
    return (now - then).total_seconds() / 3600


# ── Health check ───────────────────────────────────────────────────

def health_check() -> None:
    """Check all peers, update statuses, detect under-replicated chunks."""
    data = config.load_json(config.PEERS_FILE)
    peers = data.get("peers", {})
    token = os.environ.get("GITHUB_TOKEN", "")
    changed = False

    online = 0
    for repo, info in peers.items():
        hours = _hours_since(info.get("last_heartbeat", ""))
        old_status = info.get("status", "unknown")

        if hours < config.HEARTBEAT_STALE_HOURS:
            new_status = "online"
        elif hours < config.HEARTBEAT_DEAD_HOURS:
            new_status = "degraded"
        else:
            new_status = "offline"

        if new_status != old_status:
            print(f"  Peer {repo}: {old_status} → {new_status} (last heartbeat {hours:.1f}h ago)")
            info["status"] = new_status
            changed = True

        if new_status == "online":
            online += 1

    data["online_peers"] = online

    if changed:
        config.save_json(config.PEERS_FILE, data)
        print(f"Updated peers: {online}/{len(peers)} online")

    # Check for under-replicated chunks
    _check_replication(data, token)


def _check_replication(peers_data: dict, token: str) -> None:
    """Scan file indexes for chunks with fewer live peers than redundancy target."""
    online_repos = {
        repo for repo, info in peers_data.get("peers", {}).items()
        if info.get("status") == "online"
    }

    needs_rebalance = False
    for index_file in config.FILES_DIR.glob("*.json"):
        file_data = config.load_json(index_file)
        redundancy = file_data.get("redundancy", 1)

        for chunk_id, chunk_info in file_data.get("chunks", {}).items():
            live_peers = [p for p in chunk_info.get("peers", []) if p in online_repos]
            if len(live_peers) < redundancy:
                print(f"  Under-replicated: {file_data['filename']}/{chunk_id} "
                      f"({len(live_peers)}/{redundancy} copies)")
                needs_rebalance = True

    if needs_rebalance and token:
        callback_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if callback_repo:
            send_dispatch(token, callback_repo, "rebalance-needed", {"triggered_by": "health-check"})
            print("  Dispatched rebalance-needed")


# ── Rebalance ──────────────────────────────────────────────────────

def rebalance() -> None:
    """Redistribute chunks from dead peers to live ones."""
    data = config.load_json(config.PEERS_FILE)
    token = os.environ.get("GITHUB_TOKEN", "")

    online_repos = {
        repo for repo, info in data.get("peers", {}).items()
        if info.get("status") == "online"
    }

    if not online_repos:
        print("ERROR: No online peers available for rebalancing")
        return

    online_list = sorted(online_repos)
    rebalanced = 0

    for index_file in config.FILES_DIR.glob("*.json"):
        file_data = config.load_json(index_file)
        redundancy = file_data.get("redundancy", 1)
        filename = file_data.get("filename", "")
        file_changed = False

        for chunk_id, chunk_info in file_data.get("chunks", {}).items():
            current_peers = chunk_info.get("peers", [])
            live_peers = [p for p in current_peers if p in online_repos]
            missing = redundancy - len(live_peers)

            if missing <= 0:
                continue

            if not live_peers:
                print(f"  CRITICAL: {filename}/{chunk_id} has NO live copies!")
                continue

            # Pick source (first live peer) and targets
            source = live_peers[0]
            candidates = [p for p in online_list if p not in current_peers]

            for _ in range(missing):
                if not candidates:
                    print(f"  WARNING: Not enough peers to replicate {filename}/{chunk_id}")
                    break

                target = candidates.pop(0)
                payload = {
                    "filename": filename,
                    "chunk_id": chunk_id,
                    "target_peer": target,
                }
                if send_dispatch(token, source, "replicate-chunk", payload):
                    chunk_info["peers"].append(target)
                    file_changed = True
                    rebalanced += 1
                    print(f"  Replicate {filename}/{chunk_id}: {source} → {target}")

        if file_changed:
            config.save_json(index_file, file_data)

    print(f"Rebalance complete: {rebalanced} replications dispatched")


# ── Register / Deregister ──────────────────────────────────────────

def register_peer(peer_repo: str) -> None:
    """Add a new peer to the registry."""
    data = config.load_json(config.PEERS_FILE)
    peers = data.setdefault("peers", {})

    if peer_repo in peers:
        print(f"Peer {peer_repo} already registered")
        return

    peers[peer_repo] = PeerInfo(repo=peer_repo, joined_at=_now_iso()).to_dict()
    data["total_peers"] = len(peers)
    data["online_peers"] = sum(1 for p in peers.values() if p.get("status") == "online")
    config.save_json(config.PEERS_FILE, data)
    print(f"Registered peer: {peer_repo}")


def deregister_peer(peer_repo: str) -> None:
    """Remove a peer from the registry."""
    data = config.load_json(config.PEERS_FILE)
    peers = data.get("peers", {})

    if peer_repo not in peers:
        print(f"Peer {peer_repo} not found")
        return

    del peers[peer_repo]
    data["total_peers"] = len(peers)
    data["online_peers"] = sum(1 for p in peers.values() if p.get("status") == "online")
    config.save_json(config.PEERS_FILE, data)
    print(f"Deregistered peer: {peer_repo}")


# ── Heartbeat processing ──────────────────────────────────────────

def process_heartbeat(peer_repo: str, payload: dict) -> None:
    """Update peer info from a heartbeat callback."""
    data = config.load_json(config.PEERS_FILE)
    peers = data.setdefault("peers", {})

    if peer_repo not in peers:
        print(f"  Unknown peer {peer_repo} — auto-registering")
        peers[peer_repo] = PeerInfo(repo=peer_repo, joined_at=_now_iso()).to_dict()

    info = peers[peer_repo]
    info["status"] = "online"
    info["last_heartbeat"] = _now_iso()
    info["storage_used_mb"] = payload.get("storage_used_mb", info.get("storage_used_mb", 0))
    info["chunk_count"] = payload.get("chunk_count", info.get("chunk_count", 0))

    data["total_peers"] = len(peers)
    data["online_peers"] = sum(1 for p in peers.values() if p.get("status") == "online")
    data["used_storage_mb"] = sum(p.get("storage_used_mb", 0) for p in peers.values())

    config.save_json(config.PEERS_FILE, data)
    print(f"  Heartbeat processed: {peer_repo}")


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GitTorrent Peer Manager")
    parser.add_argument("--action", choices=["health", "rebalance", "register", "deregister", "heartbeat"], required=True)
    parser.add_argument("--peer", help="Peer repo (owner/name) for register/deregister/heartbeat")
    parser.add_argument("--payload", help="JSON payload string (for heartbeat)")
    args = parser.parse_args()

    if args.action == "health":
        health_check()
    elif args.action == "rebalance":
        rebalance()
    elif args.action == "heartbeat":
        import json
        peer = args.peer or os.environ.get("PEER_REPO", "")
        payload_str = args.payload or os.environ.get("PAYLOAD", "{}")
        if not peer:
            print("ERROR: --peer required for heartbeat")
            sys.exit(1)
        process_heartbeat(peer, json.loads(payload_str))
    elif args.action == "register":
        if not args.peer:
            print("ERROR: --peer required for register")
            sys.exit(1)
        register_peer(args.peer)
    elif args.action == "deregister":
        if not args.peer:
            print("ERROR: --peer required for deregister")
            sys.exit(1)
        deregister_peer(args.peer)


if __name__ == "__main__":
    main()
