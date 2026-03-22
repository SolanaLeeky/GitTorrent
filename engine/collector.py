"""Collect chunks from peers and reassemble files.

CLI usage (called by download.yml):
    python -m engine.collector --phase=request    # initiate download
    python -m engine.collector --phase=receive    # process incoming chunks

Request phase reads env:
    GITHUB_TOKEN, ISSUE_TITLE, ISSUE_NUMBER

Receive phase reads env:
    GITHUB_TOKEN, PAYLOAD (JSON string of client_payload)

Chunk persistence: received chunks are stored as .b64 files under
data/transfers/{transfer_id}/ and committed to git. This survives
across independent workflow runs (one per peer callback).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import config
from engine.dispatch import send_dispatch
from engine.hasher import hash_bytes, hash_file, verify_hash
from engine.models import FileIndex, TransferState
from engine.security import track_peer_failure


# ── Helpers ────────────────────────────────────────────────────────

def find_file_index(filename: str) -> FileIndex | None:
    """Load file index by filename."""
    index_path = config.FILES_DIR / f"{filename}.json"
    if not index_path.exists():
        return None
    return FileIndex.from_dict(config.load_json(index_path))


def find_transfer(transfer_id: str) -> TransferState | None:
    """Load transfer state by ID."""
    path = config.TRANSFERS_DIR / f"{transfer_id}.json"
    if not path.exists():
        return None
    return TransferState.from_dict(config.load_json(path))


def transfer_chunks_dir(transfer_id: str) -> Path:
    """Directory where received chunk .b64 files are stored for a transfer."""
    return config.TRANSFERS_DIR / transfer_id


def pick_best_peer(chunk_peers: list[str], peers_data: dict) -> str:
    """Pick the peer with best uptime/response for a chunk."""
    best = chunk_peers[0]
    best_score = float("inf")
    for repo in chunk_peers:
        info = peers_data.get("peers", {}).get(repo, {})
        if info.get("status") != "online":
            continue
        score = info.get("avg_response_ms", 9999)
        if score < best_score:
            best_score = score
            best = repo
    return best


def group_chunks_by_peer(
    file_index: FileIndex,
    peers_data: dict,
) -> dict[str, list[str]]:
    """For each chunk, pick the best peer. Group requested chunks by peer."""
    peer_requests: dict[str, list[str]] = {}
    for chunk_id, chunk_info in file_index.chunks.items():
        peer_repo = pick_best_peer(chunk_info.get("peers", []), peers_data)
        peer_requests.setdefault(peer_repo, []).append(chunk_id)
    return peer_requests


# ── Request phase ──────────────────────────────────────────────────

def create_transfer(
    file_index: FileIndex,
    requester: str,
    issue_number: int,
) -> TransferState:
    """Create a new transfer state."""
    now = datetime.now(timezone.utc)
    seq = len(list(config.TRANSFERS_DIR.glob("t_*.json"))) + 1
    transfer_id = f"{config.TRANSFER_ID_PREFIX}{now.strftime('%Y%m%d')}_{seq:03d}"

    chunks_state = {}
    for chunk_id in file_index.chunks:
        chunks_state[chunk_id] = {"status": "pending", "assigned_peer": "", "from": "", "at": ""}

    return TransferState(
        transfer_id=transfer_id,
        file_id=file_index.file_id,
        filename=file_index.filename,
        requester=requester,
        issue_number=issue_number,
        started_at=now.isoformat(),
        total_chunks=file_index.total_chunks,
        timeout_at=(now + timedelta(seconds=config.TRANSFER_TIMEOUT_SECONDS)).isoformat(),
        chunks=chunks_state,
    )


def phase_request() -> None:
    """Initiate a download: parse issue, create transfer, dispatch fetch to peers."""
    token = os.environ.get("GITHUB_TOKEN", "")
    title = os.environ.get("ISSUE_TITLE", "")
    issue_number = int(os.environ.get("ISSUE_NUMBER", "0"))
    requester = os.environ.get("GITHUB_ACTOR", "unknown")

    # Parse filename from "DOWNLOAD my-video.mp4"
    parts = title.strip().split(maxsplit=1)
    if len(parts) < 2:
        print("ERROR: Issue title must be 'DOWNLOAD <filename>'")
        sys.exit(1)
    filename = parts[1].strip()

    # Load file index
    file_index = find_file_index(filename)
    if not file_index:
        print(f"ERROR: File not found: {filename}")
        sys.exit(1)

    print(f"Downloading {filename} ({file_index.total_chunks} chunks, {file_index.size_bytes} bytes)")

    # Create transfer state
    transfer = create_transfer(file_index, requester, issue_number)
    peers_data = config.load_json(config.PEERS_FILE)
    peer_requests = group_chunks_by_peer(file_index, peers_data)

    # Update transfer with peer assignments
    for peer_repo, chunk_ids in peer_requests.items():
        for cid in chunk_ids:
            transfer.chunks[cid]["assigned_peer"] = peer_repo

    # Create chunk storage directory
    chunks_dir = transfer_chunks_dir(transfer.transfer_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / ".gitkeep").touch()

    # Save transfer state
    transfer_path = config.TRANSFERS_DIR / f"{transfer.transfer_id}.json"
    config.save_json(transfer_path, transfer.to_dict())
    print(f"  Transfer state: {transfer_path}")

    # Dispatch fetch to each peer
    callback_repo = os.environ.get("GITHUB_REPOSITORY", "")
    for peer_repo, chunk_ids in peer_requests.items():
        payload = {
            "file_id": file_index.file_id,
            "chunks_requested": chunk_ids,
            "transfer_id": transfer.transfer_id,
            "callback_repo": callback_repo,
            "callback_event": "chunks-ready",
        }
        send_dispatch(token, peer_repo, "fetch-chunks", payload)

    # Write summary for workflow
    summary = {
        "transfer_id": transfer.transfer_id,
        "filename": filename,
        "total_chunks": file_index.total_chunks,
        "peer_count": len(peer_requests),
        "size_bytes": file_index.size_bytes,
        "issue_number": issue_number,
    }
    Path("/tmp/download_request.json").write_text(json.dumps(summary))
    print(f"  Dispatched fetch to {len(peer_requests)} peers")


# ── Receive phase ──────────────────────────────────────────────────

def reassemble_file(transfer: TransferState) -> Path:
    """Reassemble chunks from committed .b64 files into the original file."""
    output_path = Path(f"/tmp/{transfer.filename}")
    chunks_dir = transfer_chunks_dir(transfer.transfer_id)
    chunk_ids = sorted(transfer.chunks.keys())

    with open(output_path, "wb") as out:
        for chunk_id in chunk_ids:
            b64_path = chunks_dir / f"{chunk_id}.b64"
            raw = base64.b64decode(b64_path.read_text())
            out.write(raw)

    return output_path


def phase_receive() -> None:
    """Process incoming chunks from a peer callback."""
    payload_str = os.environ.get("PAYLOAD", "{}")

    payload = json.loads(payload_str)
    transfer_id = payload.get("transfer_id", "")
    peer = payload.get("peer", "unknown")
    incoming_chunks = payload.get("chunks", [])

    if not transfer_id:
        print("ERROR: No transfer_id in payload")
        sys.exit(1)

    # Load transfer state
    transfer = find_transfer(transfer_id)
    if not transfer:
        print(f"ERROR: Transfer not found: {transfer_id}")
        sys.exit(1)

    # Load file index for hash verification
    file_index = find_file_index(transfer.filename)
    if not file_index:
        print(f"ERROR: File index not found: {transfer.filename}")
        sys.exit(1)

    chunks_dir = transfer_chunks_dir(transfer_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # Process each incoming chunk
    for chunk_data in incoming_chunks:
        chunk_id = chunk_data["id"]
        b64_data = chunk_data["data"]

        raw = base64.b64decode(b64_data)

        # Verify against file index hash
        expected_hash = file_index.chunks.get(chunk_id, {}).get("sha256", "")
        if not verify_hash(raw, expected_hash):
            print(f"  HASH MISMATCH: {chunk_id} from {peer} "
                  f"(expected {expected_hash[:16]}, got {hash_bytes(raw)[:16]})")
            transfer.chunks[chunk_id]["status"] = "failed"
            transfer.failed_chunks += 1
            track_peer_failure(peer)
            continue

        # Save chunk as .b64 file in repo (persists across workflow runs)
        chunk_path = chunks_dir / f"{chunk_id}.b64"
        chunk_path.write_text(b64_data)

        transfer.chunks[chunk_id]["status"] = "received"
        transfer.chunks[chunk_id]["from"] = peer
        transfer.chunks[chunk_id]["at"] = now
        transfer.received_chunks += 1
        print(f"  Chunk {chunk_id} OK from {peer}")

    # Count already-received chunks from prior callbacks (from committed .b64 files)
    existing = set(p.stem for p in chunks_dir.glob("*.b64"))
    transfer.received_chunks = len(existing)
    for cid in transfer.chunks:
        if cid in existing and transfer.chunks[cid]["status"] != "received":
            transfer.chunks[cid]["status"] = "received"

    # Save updated transfer state
    transfer_path = config.TRANSFERS_DIR / f"{transfer.transfer_id}.json"
    config.save_json(transfer_path, transfer.to_dict())

    # Check completeness
    if transfer.is_complete():
        print(f"All {transfer.total_chunks} chunks received! Reassembling...")
        output = reassemble_file(transfer)

        # Verify full file hash
        actual_hash = hash_file(output)
        if actual_hash != file_index.sha256:
            print(f"  FILE HASH MISMATCH: expected {file_index.sha256[:16]}, got {actual_hash[:16]}")
            transfer.status = "failed"
        else:
            print(f"  File hash verified: {actual_hash[:16]}...")
            transfer.status = "complete"
            print(f"  Reassembled file: {output} ({output.stat().st_size} bytes)")

            # Update download count
            file_index.download_count += 1
            index_path = config.FILES_DIR / f"{transfer.filename}.json"
            config.save_json(index_path, file_index.to_dict())

            # Update stats
            stats = config.load_json(config.STATS_FILE)
            stats["downloads"] = stats.get("downloads", 0) + 1
            config.save_json(config.STATS_FILE, stats)

        config.save_json(transfer_path, transfer.to_dict())

        # Write result for workflow to read
        result = {
            "status": transfer.status,
            "transfer_id": transfer.transfer_id,
            "filename": transfer.filename,
            "file_path": str(output),
            "size_bytes": output.stat().st_size,
            "sha256": actual_hash,
            "issue_number": transfer.issue_number,
        }
        Path("/tmp/download_result.json").write_text(json.dumps(result))
    else:
        received = transfer.received_chunks
        total = transfer.total_chunks
        print(f"  Progress: {received}/{total} chunks received")


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GitTorrent Collector")
    parser.add_argument("--phase", choices=["request", "receive"], required=True)
    args = parser.parse_args()

    if args.phase == "request":
        phase_request()
    else:
        phase_receive()


if __name__ == "__main__":
    main()
