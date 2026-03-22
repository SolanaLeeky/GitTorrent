#!/usr/bin/env python3
"""Scan the chunks/ directory and rebuild manifest.json.

Run from the peer repo root. Produces an accurate manifest of
what this peer currently holds.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CHUNKS_DIR = Path("chunks")
MANIFEST_FILE = Path("manifest.json")
CONFIG_FILE = Path("config.json")


def scan_chunks() -> dict:
    """Scan chunks/ and return {filename: {chunks: [...], total_size_mb: N}}."""
    result = {}
    if not CHUNKS_DIR.exists():
        return result

    for file_dir in sorted(CHUNKS_DIR.iterdir()):
        if not file_dir.is_dir():
            continue
        filename = file_dir.name
        chunk_ids = []
        total_bytes = 0
        for chunk_file in sorted(file_dir.glob("*.b64")):
            chunk_id = chunk_file.stem  # e.g. "chunk_000"
            chunk_ids.append(chunk_id)
            total_bytes += chunk_file.stat().st_size

        if chunk_ids:
            result[filename] = {
                "chunks": chunk_ids,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            }

    return result


def calc_storage_used() -> float:
    """Total MB used by all chunk files."""
    if not CHUNKS_DIR.exists():
        return 0.0
    total = sum(f.stat().st_size for f in CHUNKS_DIR.rglob("*.b64"))
    return round(total / (1024 * 1024), 2)


def main() -> None:
    # Load existing manifest and config
    manifest = {}
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE) as f:
            manifest = json.load(f)

    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)

    # Rebuild
    chunks_map = scan_chunks()
    storage_used = calc_storage_used()
    chunk_count = sum(len(v["chunks"]) for v in chunks_map.values())

    # Determine peer_id from GITHUB_REPOSITORY env or existing manifest
    peer_id = os.environ.get("GITHUB_REPOSITORY", manifest.get("peer_id", ""))

    manifest.update({
        "peer_id": peer_id,
        "tracker": cfg.get("tracker_repo", manifest.get("tracker", "")),
        "storage_limit_mb": cfg.get("storage_limit_mb", 2000),
        "storage_used_mb": storage_used,
        "chunk_count": chunk_count,
        "chunks": chunks_map,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })

    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"Manifest updated: {chunk_count} chunks, {storage_used} MB used")


if __name__ == "__main__":
    main()
