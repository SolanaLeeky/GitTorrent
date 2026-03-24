# GitTorrent

> P2P file sharing built on GitHub Actions + `repository_dispatch`

*Dashboard updated: 2026-03-24 15:17 UTC*

## Network Status

| Metric | Value |
|--------|-------|
| Peers | **3** online / 0 degraded / 0 offline |
| Storage | 0 MB / 6000 MB |
| Files | 2 |
| Uploads | 3 |
| Downloads | 1 |
| Redundancy | 2x |
| Encryption | Disabled |

## Files

| Filename | Size | Chunks | Downloads | Uploaded | Expires |
|----------|------|--------|-----------|----------|---------|
| `gists.txt` | 9.4 KB | 1 | 0 | 2026-03-22 | 2026-04-21 |
| `test-upload.txt` | 93 B | 1 | 1 | 2026-03-22 | 2026-04-21 |

## Peers

| Peer | Status | Storage | Chunks | Uptime | Last Seen |
|------|--------|---------|--------|--------|-----------|
| `SolanaLeeky/peer-node-01` | 🟢 online | 0/2000 MB | 1 | 100.0% | 2026-03-24T13:40 |
| `SolanaLeeky/peer-node-02` | 🟢 online | 0/2000 MB | 1 | 100.0% | 2026-03-24T13:07 |
| `SolanaLeeky/peer-node-03` | 🟢 online | 0/2000 MB | 0 | 100.0% | 2026-03-24T13:11 |

## How to Use

### Upload a file
1. Open a new issue titled `UPLOAD <filename>`
2. Attach your file in the issue body
3. The system splits it into chunks and distributes to peers

### Download a file
1. Open a new issue titled `DOWNLOAD <filename>`
2. Chunks are fetched from peers and reassembled
3. The file is delivered as a GitHub Release

### Add a peer
1. Run `./peer/setup.sh <owner/peer-repo> <owner/tracker-repo>`
2. Open an issue titled `REGISTER_PEER <owner/peer-repo>`

## Architecture

```
Issue (UPLOAD/DOWNLOAD)
  → Tracker workflow (split/collect)
    → repository_dispatch
      → Peer workflows (store/fetch)
        → Chunks as committed .b64 files
          → GitHub Release (delivery)
```

Each repo is a seeder. The tracker is a repo. The protocol is `repository_dispatch`.
