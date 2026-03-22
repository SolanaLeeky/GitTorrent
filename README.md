# GitTorrent

> P2P file sharing built on GitHub Actions + `repository_dispatch`

*Dashboard updated: 2026-03-22 08:09 UTC*

## Network Status

| Metric | Value |
|--------|-------|
| Peers | **0** online / 0 degraded / 0 offline |
| Storage | 0 MB / 0 MB |
| Files | 0 |
| Uploads | 0 |
| Downloads | 0 |
| Redundancy | 2x |
| Encryption | Disabled |

## Files

*No files shared yet. Open an issue titled `UPLOAD <filename>` to share a file.*

## Peers

*No peers registered. Run `peer/setup.sh` to add a peer node.*

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
