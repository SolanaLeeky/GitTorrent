"""Assign chunks to peers and dispatch store-chunks events.

Used by chunker.py during the upload flow.
"""

from __future__ import annotations

import os

from engine import config
from engine.dispatch import send_dispatch
from engine.models import ChunkInfo, PeerInfo
from engine.security import is_peer_blacklisted


def load_online_peers() -> list[PeerInfo]:
    """Load peers.json and return online, non-blacklisted peers sorted by least storage used."""
    data = config.load_json(config.PEERS_FILE)
    peers = []
    for repo, info in data.get("peers", {}).items():
        peer = PeerInfo.from_dict(repo, info)
        if peer.status == "online" and not is_peer_blacklisted(repo):
            peers.append(peer)
    peers.sort(key=lambda p: p.storage_used_mb)
    return peers


def assign_chunks_to_peers(
    chunks: list[ChunkInfo],
    peers: list[PeerInfo],
    redundancy: int = config.DEFAULT_REDUNDANCY,
) -> dict[str, list[str]]:
    """Round-robin assign chunks to peers.

    Returns:
        Dict mapping chunk_id → list of peer repos.
    """
    if not peers:
        print("WARNING: No online peers available — chunks will be unassigned")
        return {}

    assignment: dict[str, list[str]] = {}
    for i, chunk in enumerate(chunks):
        assigned_peers = []
        for r in range(redundancy):
            peer_idx = (i + r) % len(peers)
            assigned_peers.append(peers[peer_idx].repo)
        assignment[chunk.chunk_id] = assigned_peers

    return assignment


def group_by_peer(
    chunks: list[ChunkInfo],
    assignment: dict[str, list[str]],
) -> dict[str, list[ChunkInfo]]:
    """Group chunks by which peer they're assigned to.

    Returns:
        Dict mapping peer_repo → list of ChunkInfo to send to that peer.
    """
    peer_chunks: dict[str, list[ChunkInfo]] = {}
    for chunk in chunks:
        for peer_repo in assignment.get(chunk.chunk_id, []):
            peer_chunks.setdefault(peer_repo, []).append(chunk)
    return peer_chunks


def dispatch_to_peers(
    peer_chunks: dict[str, list[ChunkInfo]],
    file_id: str,
    filename: str,
    callback_repo: str,
    token: str,
) -> int:
    """Send store-chunks dispatch to each peer. Returns count of successful dispatches."""
    success = 0
    for peer_repo, chunks in peer_chunks.items():
        payload = {
            "file_id": file_id,
            "filename": filename,
            "chunks": [
                {
                    "id": c.chunk_id,
                    "data": c.data_b64,
                    "sha256": c.sha256,
                }
                for c in chunks
            ],
            "callback_repo": callback_repo,
            "callback_event": "store-confirm",
        }
        if send_dispatch(token, peer_repo, "store-chunks", payload):
            success += 1
    return success


def distribute_chunks(
    chunks: list[ChunkInfo],
    token: str,
    filename: str = "",
    file_id: str = "",
    redundancy: int = config.DEFAULT_REDUNDANCY,
) -> dict[str, list[str]]:
    """Full distribution pipeline: load peers, assign, dispatch.

    Returns:
        chunk_id → list of peer repos mapping.
    """
    peers = load_online_peers()
    if not peers:
        print("WARNING: No online peers — skipping dispatch (chunks unassigned)")
        return {}

    # Determine callback repo from env or config
    callback_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not callback_repo:
        cfg = config.load_json(config.CONFIG_FILE)
        callback_repo = cfg.get("tracker_repo", "")

    assignment = assign_chunks_to_peers(chunks, peers, redundancy)
    peer_groups = group_by_peer(chunks, assignment)

    if not file_id:
        file_id = f"{config.FILE_ID_PREFIX}{chunks[0].sha256[:8]}" if chunks else "f_unknown"

    print(f"  Distributing {len(chunks)} chunks to {len(peer_groups)} peers...")
    dispatched = dispatch_to_peers(peer_groups, file_id, filename, callback_repo, token)
    print(f"  → {dispatched}/{len(peer_groups)} dispatches succeeded")

    return assignment
