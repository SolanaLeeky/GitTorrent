"""Split a file into chunks, hash each, produce a FileIndex.

CLI usage (called by upload.yml):
    python -m engine.chunker

Reads env:
    GITHUB_TOKEN   — PAT for dispatch calls
    ISSUE_NUMBER   — issue that triggered the upload
    UPLOADER       — github username of uploader

Expects the downloaded file at /tmp/upload/ (placed by download_attachment.py).
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import config
from engine.hasher import hash_bytes, hash_file
from engine.models import ChunkInfo, FileIndex


def split_file(filepath: Path, chunk_size: int = config.CHUNK_SIZE) -> list[ChunkInfo]:
    """Split a file into sized chunks. Returns list of ChunkInfo with b64 data."""
    chunks: list[ChunkInfo] = []
    idx = 0
    with open(filepath, "rb") as f:
        while True:
            raw = f.read(chunk_size)
            if not raw:
                break
            chunk = ChunkInfo(
                chunk_id=f"chunk_{idx:03d}",
                sha256=hash_bytes(raw),
                size_bytes=len(raw),
                data_b64=base64.b64encode(raw).decode("ascii"),
            )
            chunks.append(chunk)
            idx += 1
    return chunks


def build_file_index(
    filepath: Path,
    chunks: list[ChunkInfo],
    uploader: str,
    redundancy: int = config.DEFAULT_REDUNDANCY,
    expiry_days: int = 30,
) -> FileIndex:
    """Build a FileIndex from a file and its chunks."""
    file_hash = hash_file(filepath)
    now = datetime.now(timezone.utc)
    file_id = f"{config.FILE_ID_PREFIX}{file_hash[:8]}"

    chunk_map = {}
    for c in chunks:
        chunk_map[c.chunk_id] = {
            "sha256": c.sha256,
            "size_bytes": c.size_bytes,
            "peers": list(c.peers),
            "status": c.status,
        }

    return FileIndex(
        file_id=file_id,
        filename=filepath.name,
        size_bytes=filepath.stat().st_size,
        chunk_size_bytes=config.CHUNK_SIZE,
        total_chunks=len(chunks),
        sha256=file_hash,
        uploaded_by=uploader,
        uploaded_at=now.isoformat(),
        expires_at=(now + timedelta(days=expiry_days)).isoformat(),
        redundancy=redundancy,
        status="healthy",
        chunks=chunk_map,
    )


def main() -> None:
    """CLI entry point: split file, distribute chunks, write file index."""
    import json as _json
    from engine.distributor import distribute_chunks

    upload_dir = Path("/tmp/upload")
    files = list(upload_dir.iterdir())
    if not files:
        print("ERROR: No file found in /tmp/upload/")
        sys.exit(1)

    filepath = files[0]
    uploader = os.environ.get("UPLOADER", "unknown")
    token = os.environ.get("GITHUB_TOKEN", "")

    print(f"Splitting {filepath.name} ({filepath.stat().st_size} bytes)...")
    chunks = split_file(filepath)
    print(f"  → {len(chunks)} chunks of {config.CHUNK_SIZE} bytes each")

    # Build file index first so we have file_id
    file_index = build_file_index(filepath, chunks, uploader)

    # Distribute chunks to peers
    print("Distributing chunks to peers...")
    chunk_peer_map = distribute_chunks(
        chunks, token, filename=filepath.name, file_id=file_index.file_id,
    )

    # Update chunk peer assignments in index
    for chunk in chunks:
        if chunk.chunk_id in chunk_peer_map:
            chunk.peers = chunk_peer_map[chunk.chunk_id]
            chunk.status = "stored"
            file_index.chunks[chunk.chunk_id]["peers"] = chunk.peers
            file_index.chunks[chunk.chunk_id]["status"] = "stored"

    # Save file index
    index_path = config.FILES_DIR / f"{filepath.name}.json"
    config.save_json(index_path, file_index.to_dict())
    print(f"  → File index written to {index_path}")

    # Update stats
    stats = config.load_json(config.STATS_FILE)
    stats["uploads"] = stats.get("uploads", 0) + 1
    stats["total_chunks_stored"] = stats.get("total_chunks_stored", 0) + len(chunks)
    stats["total_bytes_transferred"] = (
        stats.get("total_bytes_transferred", 0) + filepath.stat().st_size
    )
    config.save_json(config.STATS_FILE, stats)

    # Write summary for workflow to read
    peer_count = len(set(p for peers in chunk_peer_map.values() for p in peers))
    summary = {
        "file_id": file_index.file_id,
        "filename": filepath.name,
        "size_bytes": file_index.size_bytes,
        "total_chunks": file_index.total_chunks,
        "peer_count": peer_count,
        "sha256": file_index.sha256,
    }
    summary_path = Path("/tmp/upload_summary.json")
    summary_path.write_text(_json.dumps(summary))

    print(f"Upload complete: {file_index.file_id} — {len(chunks)} chunks across {peer_count} peers")


if __name__ == "__main__":
    main()
