"""Constants and JSON helpers for GitTorrent."""

import json
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
REPO_ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent.parent))
DATA_DIR = REPO_ROOT / "data"
FILES_DIR = DATA_DIR / "files"
TRANSFERS_DIR = DATA_DIR / "transfers"
PEERS_FILE = DATA_DIR / "peers.json"
STATS_FILE = DATA_DIR / "stats.json"
CONFIG_FILE = DATA_DIR / "config.json"

# ── Chunking ───────────────────────────────────────────────────────
CHUNK_SIZE = 40 * 1024  # 40 KB raw → ~53 KB base64 (fits in 65 KB dispatch)
DEFAULT_REDUNDANCY = 2  # copies per chunk for fault tolerance

# ── Timeouts ───────────────────────────────────────────────────────
TRANSFER_TIMEOUT_SECONDS = 600  # 10 minutes
HEARTBEAT_STALE_HOURS = 12      # mark degraded
HEARTBEAT_DEAD_HOURS = 24       # mark offline

# ── IDs ────────────────────────────────────────────────────────────
FILE_ID_PREFIX = "f_"
TRANSFER_ID_PREFIX = "t_"


def load_json(path: Path) -> dict:
    """Load a JSON file. Returns empty dict if missing."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Write dict to JSON file, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
