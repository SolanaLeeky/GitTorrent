"""SHA-256 hashing for files and chunks."""

import hashlib
from pathlib import Path

BUFFER_SIZE = 64 * 1024  # 64 KB read buffer


def hash_file(path: Path) -> str:
    """Return hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(BUFFER_SIZE)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Return hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def verify_hash(data: bytes, expected: str) -> bool:
    """Check that data matches expected SHA-256 hex digest."""
    return hash_bytes(data) == expected
