"""Data models for GitTorrent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChunkInfo:
    """A single chunk of a file."""
    chunk_id: str           # e.g. "chunk_000"
    sha256: str             # hash of raw bytes
    size_bytes: int         # raw size
    data_b64: str = ""      # base64-encoded content (empty when stored on disk)
    peers: list[str] = field(default_factory=list)  # repos holding this chunk
    status: str = "pending" # pending | stored | healthy | missing


@dataclass
class FileIndex:
    """Metadata for a shared file — stored as data/files/{filename}.json."""
    file_id: str
    filename: str
    size_bytes: int
    chunk_size_bytes: int
    total_chunks: int
    sha256: str             # hash of full original file
    uploaded_by: str
    uploaded_at: str        # ISO 8601
    expires_at: str         # ISO 8601
    redundancy: int
    status: str             # healthy | degraded | partial
    download_count: int = 0
    chunks: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "chunk_size_bytes": self.chunk_size_bytes,
            "total_chunks": self.total_chunks,
            "sha256": self.sha256,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at,
            "expires_at": self.expires_at,
            "redundancy": self.redundancy,
            "status": self.status,
            "download_count": self.download_count,
            "chunks": self.chunks,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FileIndex:
        return cls(**d)


@dataclass
class PeerInfo:
    """A single peer node."""
    repo: str               # e.g. "user/peer-node-01"
    status: str = "online"  # online | degraded | offline
    last_heartbeat: str = ""
    storage_used_mb: float = 0
    storage_limit_mb: float = 2000
    chunk_count: int = 0
    uptime_pct: float = 100.0
    avg_response_ms: float = 0
    total_fetches: int = 0
    failed_fetches: int = 0
    joined_at: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "storage_used_mb": self.storage_used_mb,
            "storage_limit_mb": self.storage_limit_mb,
            "chunk_count": self.chunk_count,
            "uptime_pct": self.uptime_pct,
            "avg_response_ms": self.avg_response_ms,
            "total_fetches": self.total_fetches,
            "failed_fetches": self.failed_fetches,
            "joined_at": self.joined_at,
        }

    @classmethod
    def from_dict(cls, repo: str, d: dict) -> PeerInfo:
        return cls(repo=repo, **d)


@dataclass
class TransferState:
    """Active download state — stored as data/transfers/{id}.json."""
    transfer_id: str
    file_id: str
    filename: str
    requester: str
    issue_number: int
    started_at: str
    status: str = "in_progress"  # in_progress | complete | failed | timeout
    total_chunks: int = 0
    received_chunks: int = 0
    failed_chunks: int = 0
    timeout_at: str = ""
    chunks: dict[str, dict] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return self.received_chunks >= self.total_chunks

    def to_dict(self) -> dict:
        return {
            "transfer_id": self.transfer_id,
            "file_id": self.file_id,
            "filename": self.filename,
            "requester": self.requester,
            "issue_number": self.issue_number,
            "started_at": self.started_at,
            "status": self.status,
            "total_chunks": self.total_chunks,
            "received_chunks": self.received_chunks,
            "failed_chunks": self.failed_chunks,
            "timeout_at": self.timeout_at,
            "chunks": self.chunks,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TransferState:
        return cls(**d)
