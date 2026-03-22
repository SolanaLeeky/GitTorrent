# GitTorrent — Implementation Plan

> BitTorrent built on GitHub Actions + repository_dispatch
> 6 phases, each builds on the previous one.

---

## Phase 1: Core Engine (`engine/`)

Build all Python modules that the workflows will call. No workflows yet — just the logic, testable locally.

### Files to create

| File | Purpose |
|------|---------|
| `engine/__init__.py` | Package init |
| `engine/config.py` | Constants (chunk size, timeouts, paths), load/save JSON helpers |
| `engine/hasher.py` | SHA-256 for files and chunks, verify hash |
| `engine/chunker.py` | Split file into chunks, hash each, return chunk manifest |
| `engine/distributor.py` | Read peers.json, select peers round-robin, assign chunks, call dispatch |
| `engine/collector.py` | Two modes: `--phase=request` (send fetch dispatches) and `--phase=receive` (decode incoming chunks, verify, reassemble) |
| `engine/dispatch.py` | Thin wrapper around `repository_dispatch` API (POST to peer/tracker) |
| `engine/peer_manager.py` | Health check logic, rebalance logic, peer registration |
| `engine/download_attachment.py` | Parse GitHub issue body for attachment URL, download file |
| `engine/models.py` | Dataclass definitions for FileIndex, ChunkInfo, PeerInfo, TransferState |
| `requirements.txt` | `PyGithub`, `requests` |

### Key decisions

- **Chunk size**: 40 KB raw (fits in ~53 KB base64 within 65 KB dispatch limit). This is the "pure dispatch" path — no artifacts needed for MVP.
- **Redundancy**: Default 1 for MVP (single copy per chunk). Phase 5 adds redundancy=2.
- **Encoding**: Base64 for chunk data in dispatch payloads.
- **File ID**: `f_` + first 8 chars of file SHA-256.
- **Transfer ID**: `t_` + ISO date + `_` + 3-digit sequence.

### Data directory bootstrap

Create seed data files so workflows have something to read:

```
data/
├── files/          # empty dir (will hold file indexes)
├── transfers/      # empty dir (will hold active transfers)
├── peers.json      # empty peer registry: {"peers": {}, "total_peers": 0, ...}
└── stats.json      # empty stats: {"uploads": 0, "downloads": 0, ...}
```

### Done when

- `chunker.py` can split a local file, produce a chunk manifest with hashes
- `collector.py --phase=receive` can reassemble chunks and verify the full file hash
- All modules import cleanly, no syntax errors
- A simple integration test: split a file → reassemble → SHA-256 matches

---

## Phase 2: Peer Node Repos

Build the peer-side repo structure and all peer workflows. The tracker doesn't exist yet — we're building the "storage nodes" first.

### Files to create

| File | Purpose |
|------|---------|
| `peer/store.yml` | Workflow: `repository_dispatch[store-chunks]` → decode payload → write .b64 files → commit → confirm back |
| `peer/fetch.yml` | Workflow: `repository_dispatch[fetch-chunks]` → read .b64 files → dispatch `chunks-ready` callback |
| `peer/heartbeat.yml` | Workflow: cron every 6h → dispatch `peer-heartbeat` to tracker |
| `peer/replicate.yml` | Workflow: `repository_dispatch[replicate-chunk]` → read chunk → dispatch `store-chunks` to target peer |
| `peer/prune.yml` | Workflow: cron daily → delete chunks older than expiry → commit |
| `peer/manifest.json` | Seed manifest (empty chunks list) |
| `peer/config.json` | Peer config template (tracker repo, storage limit, etc.) |
| `peer/update_manifest.py` | Script: scan `chunks/` directory, rebuild manifest.json |
| `peer/setup.sh` | Script: create a new peer repo from this template (gh repo create + push + add secret) |

All peer workflows live under `peer/` in this repo as templates. The `setup.sh` script copies them into a real peer repo.

### Workflow details

**store.yml** — the most important peer workflow:
1. Triggered by `repository_dispatch` type `store-chunks`
2. Checkout repo
3. Parse `client_payload` → extract filename, chunks array
4. For each chunk: write `chunks/{filename}/{chunk_id}.b64`, verify hash
5. Run `update_manifest.py` to rebuild manifest
6. Commit + push
7. Dispatch `store-confirm` back to `client_payload.callback_repo`

**fetch.yml**:
1. Triggered by `repository_dispatch` type `fetch-chunks`
2. Parse `client_payload` → extract `chunks_requested` list
3. For each requested chunk: read .b64 file, compute hash
4. Dispatch `chunks-ready` back to `client_payload.callback_repo` with chunk data

**heartbeat.yml**:
1. Cron: `0 */6 * * *`
2. Checkout repo, read manifest.json
3. Dispatch `peer-heartbeat` to tracker with storage stats

### Done when

- All workflow YAML files are valid (pass `actionlint` if available)
- `update_manifest.py` correctly scans chunks/ and produces valid manifest.json
- `setup.sh` can create a peer repo skeleton (tested with `--dry-run`)

---

## Phase 3: Upload Flow (Tracker Side)

Wire up the tracker's upload pipeline: issue opened → file split → chunks dispatched to peers.

### Files to create

| File | Purpose |
|------|---------|
| `.github/workflows/upload.yml` | Tracker workflow: issue trigger → download attachment → split → distribute → commit index → close issue |
| `.github/ISSUE_TEMPLATE/upload.yml` | Issue template for uploads |

### Workflow: upload.yml

Trigger: `issues.opened` where title starts with `UPLOAD`

Steps:
1. Checkout tracker repo
2. Setup Python 3.11, install deps
3. Run `engine/download_attachment.py` — parse issue body for attachment URL, download to `/tmp/upload/`
4. Run `engine/chunker.py` — split file, hash chunks
5. Run `engine/distributor.py` — load peers.json, assign chunks round-robin, dispatch `store-chunks` to each peer
6. Write file index to `data/files/{filename}.json`
7. Commit + push data changes
8. Comment on issue with receipt (file ID, chunk count, peer count)
9. Close issue

### download_attachment.py details

GitHub issue attachments are uploaded to `https://github.com/user-attachments/assets/...`. The script:
1. Reads `ISSUE_BODY` env var
2. Regex extracts URLs matching GitHub's attachment pattern
3. Downloads the first match to `/tmp/upload/`
4. Returns the local file path and original filename

### distributor.py details

1. Reads `data/peers.json`
2. Filters peers where `status == "online"` and `accept_new_chunks == true`
3. Sorts by `storage_used_mb` ascending (least loaded first)
4. Assigns chunks round-robin across available peers
5. For each peer: calls `dispatch.py` with event `store-chunks` and payload containing all assigned chunks
6. Returns the chunk-to-peer mapping for the file index

### Done when

- Opening an issue titled "UPLOAD test.txt" with a file attachment triggers the full upload pipeline
- File index JSON is committed to `data/files/`
- Peer repos receive `store-chunks` dispatch and store the chunk files
- Issue is closed with a receipt comment

---

## Phase 4: Download Flow (Tracker Side)

Wire up the download pipeline: issue opened → fetch from peers → reassemble → deliver via release.

### Files to create

| File | Purpose |
|------|---------|
| `.github/workflows/download.yml` | Tracker workflow: two jobs — `initiate` (issue trigger) and `collect` (dispatch callback) |
| `.github/ISSUE_TEMPLATE/download.yml` | Issue template for downloads |

### Workflow: download.yml

**Job 1 — `initiate`** (trigger: issue opened with "DOWNLOAD"):
1. Checkout repo
2. Run `engine/collector.py --phase=request`
   - Parse filename from issue title
   - Load file index from `data/files/{filename}.json`
   - Group chunks by peer (pick best peer per chunk by uptime/response time)
   - Create transfer state in `data/transfers/{transfer_id}.json`
   - Dispatch `fetch-chunks` to each relevant peer
3. Commit transfer state
4. Comment on issue: "Download initiated, fetching from N peers..."

**Job 2 — `collect`** (trigger: `repository_dispatch[chunks-ready]`):
1. Checkout repo
2. Run `engine/collector.py --phase=receive`
   - Decode chunks from `client_payload`
   - Verify SHA-256 of each chunk
   - Save chunk data to `/tmp/chunks/`
   - Update transfer state (mark chunks as received)
   - Check completeness: if all chunks received →
     - Reassemble: `cat chunk_00 chunk_01 ... > original_file`
     - Verify full file SHA-256
     - Create GitHub Release with file as asset
     - Close original issue with release link
   - If not complete: commit updated transfer state, wait for more callbacks
3. Commit updated state

### Transfer state management

The tricky part: the `collect` job runs once per peer callback. Each run is independent (no shared memory between workflow runs). State is managed through git commits:

1. Each `collect` run checks out the latest repo state
2. Reads transfer JSON to see what's already received
3. Adds newly received chunks
4. Commits + pushes
5. Race condition mitigation: use `git pull --rebase` before push, retry on conflict

### Done when

- Opening an issue titled "DOWNLOAD test.txt" triggers fetch dispatches to peers
- Peer callbacks deliver chunks back to tracker
- After all chunks arrive: file is reassembled, hash verified, release created
- Issue is closed with download link

---

## Phase 5: Health, Rebalancing & Maintenance

Add the operational workflows that keep the network healthy.

### Files to create

| File | Purpose |
|------|---------|
| `.github/workflows/health-check.yml` | Cron + dispatch: check all peers, mark status, detect under-replicated chunks |
| `.github/workflows/rebalance.yml` | Dispatch trigger: redistribute chunks from dead peers to live ones |
| `.github/workflows/cleanup.yml` | Cron: delete expired file indexes and dispatch prune to peers |
| `.github/workflows/register-peer.yml` | Issue trigger: "REGISTER_PEER repo/name" → add to peers.json |

### health-check.yml

Trigger: cron every 6 hours + `repository_dispatch[peer-heartbeat]`

For heartbeat callbacks:
1. Update the peer's entry in peers.json (last_heartbeat, storage stats)
2. Commit

For cron runs:
1. Load peers.json
2. For each peer:
   - If `last_heartbeat` > 12h ago → mark `degraded`
   - If `last_heartbeat` > 24h ago → mark `offline`
3. Scan all file indexes for chunks on offline peers
4. If any chunk has < redundancy live copies → dispatch `rebalance-needed`
5. Commit updated peers.json

### rebalance.yml

Trigger: `repository_dispatch[rebalance-needed]`

1. Load affected file indexes
2. For each under-replicated chunk:
   - Find a surviving peer that has it
   - Find a target peer with available storage
   - Dispatch `replicate-chunk` to surviving peer (peer-to-peer copy)
3. Update file index with new peer locations
4. Commit

### cleanup.yml

Trigger: cron daily

1. Scan `data/files/*.json` for `expires_at < now`
2. For each expired file:
   - Dispatch `prune-file` to all peers holding its chunks
   - Delete the file index JSON
3. Clean up completed transfers in `data/transfers/`
4. Commit

### register-peer.yml

Trigger: issue opened with "REGISTER_PEER" or "DEREGISTER_PEER"

Registration:
1. Verify the peer repo exists (API call)
2. Add entry to peers.json with status "online"
3. Close issue with confirmation

Deregistration:
1. Mark peer as "decommissioning" in peers.json
2. Trigger rebalance to relocate all chunks
3. After relocation: remove peer from peers.json
4. Close issue

### Redundancy upgrade

Update `distributor.py` to support `redundancy` parameter:
- Default: 2 (each chunk goes to 2 peers)
- Each chunk assigned to `redundancy` different peers
- File index tracks all peer copies per chunk

### Done when

- Peer heartbeats update peers.json automatically
- Stale peers are detected and marked offline
- Under-replicated chunks trigger rebalancing
- Expired files are cleaned up
- New peers can join via issue

---

## Phase 6: Security, Polish & Dashboard

Harden the system and make it user-friendly.

### Security

| Feature | Implementation |
|---------|---------------|
| **Upload allowlist** | `data/config.json` with `authorized_uploaders` list. `upload.yml` checks issue author against list. |
| **Chunk verification** | Already built in Phase 1 (SHA-256). Ensure every fetch path verifies. |
| **Transfer ID uniqueness** | `collector.py` checks transfer ID hasn't been used before (prevents replay). |
| **Peer blacklist** | If a peer serves N bad chunks, add to `blacklisted_peers` in peers.json. Skip in distributor. |
| **Rate limiting** | Track dispatches per hour in stats.json. Refuse new uploads if approaching 5,000/hr limit. |

### Optional encryption

For sensitive files:
1. `engine/crypto.py` — AES-256-GCM encrypt/decrypt
2. Upload flow: encrypt each chunk before dispatching (key stays on tracker)
3. Download flow: decrypt after reassembly
4. Key stored as repo secret, never sent to peers

### Dashboard README

Auto-generate `README.md` as a network dashboard:
- `.github/workflows/dashboard.yml` — cron every hour
- Reads peers.json, stats.json, file indexes
- Generates markdown with: network status, file list, peer list, storage usage
- Commits updated README.md

### Issue templates

**upload.yml** template:
```yaml
name: Upload File
description: Share a file on the GitTorrent network
title: "UPLOAD "
body:
  - type: markdown
    attributes:
      value: "Attach your file below. Max 100 MB."
  - type: textarea
    attributes:
      label: File
      description: Drag and drop your file here
```

**download.yml** template:
```yaml
name: Download File
description: Download a file from the GitTorrent network
title: "DOWNLOAD "
body:
  - type: input
    attributes:
      label: Filename
      description: The exact filename to download
```

### Final polish

- Error handling in all engine modules (graceful failures, retry logic)
- Logging throughout (print statements that show in Actions logs)
- `data/config.json` for all tunable parameters
- Git concurrency groups on tracker workflows to prevent race conditions

### Done when

- Unauthorized uploads are rejected
- Bad chunks from malicious peers are detected and re-fetched
- README shows live network status
- End-to-end test: upload a file → download it → verify identical

---

## Phase Summary

| Phase | What | Key Output | Depends On |
|-------|------|-----------|------------|
| 1 | Core Engine | Python modules in `engine/`, data seed files | Nothing |
| 2 | Peer Node | Workflow YAMLs + scripts in `peer/`, setup script | Phase 1 (models) |
| 3 | Upload Flow | `upload.yml` workflow, issue template | Phase 1 + 2 |
| 4 | Download Flow | `download.yml` workflow, issue template | Phase 1 + 2 + 3 |
| 5 | Health & Rebalancing | Maintenance workflows, redundancy | Phase 1-4 |
| 6 | Security & Polish | Auth, encryption, dashboard, error handling | Phase 1-5 |

### File tree at completion

```
GitTorrent/
├── .github/
│   ├── workflows/
│   │   ├── upload.yml
│   │   ├── download.yml
│   │   ├── health-check.yml
│   │   ├── rebalance.yml
│   │   ├── cleanup.yml
│   │   ├── register-peer.yml
│   │   └── dashboard.yml
│   └── ISSUE_TEMPLATE/
│       ├── upload.yml
│       └── download.yml
├── engine/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── hasher.py
│   ├── chunker.py
│   ├── distributor.py
│   ├── collector.py
│   ├── dispatch.py
│   ├── peer_manager.py
│   ├── download_attachment.py
│   └── crypto.py
├── peer/
│   ├── store.yml
│   ├── fetch.yml
│   ├── heartbeat.yml
│   ├── replicate.yml
│   ├── prune.yml
│   ├── manifest.json
│   ├── config.json
│   ├── update_manifest.py
│   └── setup.sh
├── data/
│   ├── files/
│   │   └── .gitkeep
│   ├── transfers/
│   │   └── .gitkeep
│   ├── peers.json
│   ├── stats.json
│   └── config.json
├── requirements.txt
├── plan.md
└── README.md
```
