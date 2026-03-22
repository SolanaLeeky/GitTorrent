"""Generate README.md as a live network dashboard.

CLI usage (called by dashboard.yml):
    python -m engine.dashboard
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine import config


def generate_dashboard() -> str:
    """Build the full README.md markdown content."""
    peers_data = config.load_json(config.PEERS_FILE)
    stats = config.load_json(config.STATS_FILE)
    cfg = config.load_json(config.CONFIG_FILE)

    peers = peers_data.get("peers", {})
    online = sum(1 for p in peers.values() if p.get("status") == "online")
    degraded = sum(1 for p in peers.values() if p.get("status") == "degraded")
    offline = sum(1 for p in peers.values() if p.get("status") == "offline")
    total_storage = sum(p.get("storage_limit_mb", 0) for p in peers.values())
    used_storage = sum(p.get("storage_used_mb", 0) for p in peers.values())

    # File catalog
    files = []
    for index_file in sorted(config.FILES_DIR.glob("*.json")):
        data = config.load_json(index_file)
        if data.get("filename"):
            files.append(data)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append("# GitTorrent")
    lines.append("")
    lines.append("> P2P file sharing built on GitHub Actions + `repository_dispatch`")
    lines.append("")
    lines.append(f"*Dashboard updated: {now}*")
    lines.append("")

    # ── Network status
    lines.append("## Network Status")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Peers | **{online}** online / {degraded} degraded / {offline} offline |")
    lines.append(f"| Storage | {used_storage:.0f} MB / {total_storage:.0f} MB |")
    lines.append(f"| Files | {len(files)} |")
    lines.append(f"| Uploads | {stats.get('uploads', 0)} |")
    lines.append(f"| Downloads | {stats.get('downloads', 0)} |")
    lines.append(f"| Redundancy | {cfg.get('default_redundancy', 2)}x |")
    lines.append(f"| Encryption | {'Enabled' if cfg.get('encryption_enabled') else 'Disabled'} |")
    lines.append("")

    # ── File catalog
    lines.append("## Files")
    lines.append("")
    if files:
        lines.append("| Filename | Size | Chunks | Downloads | Uploaded | Expires |")
        lines.append("|----------|------|--------|-----------|----------|---------|")
        for f in files:
            size = f.get("size_bytes", 0)
            if size >= 1024 * 1024:
                size_str = f"{size / (1024*1024):.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            uploaded = f.get("uploaded_at", "")[:10]
            expires = f.get("expires_at", "")[:10]
            lines.append(
                f"| `{f['filename']}` | {size_str} | {f.get('total_chunks', 0)} "
                f"| {f.get('download_count', 0)} | {uploaded} | {expires} |"
            )
    else:
        lines.append("*No files shared yet. Open an issue titled `UPLOAD <filename>` to share a file.*")
    lines.append("")

    # ── Peer list
    lines.append("## Peers")
    lines.append("")
    if peers:
        lines.append("| Peer | Status | Storage | Chunks | Uptime | Last Seen |")
        lines.append("|------|--------|---------|--------|--------|-----------|")
        for repo, info in sorted(peers.items()):
            status = info.get("status", "unknown")
            status_icon = {"online": "🟢", "degraded": "🟡", "offline": "🔴"}.get(status, "⚪")
            used = info.get("storage_used_mb", 0)
            limit = info.get("storage_limit_mb", 0)
            chunks = info.get("chunk_count", 0)
            uptime = info.get("uptime_pct", 0)
            last_hb = info.get("last_heartbeat", "never")[:16]
            lines.append(
                f"| `{repo}` | {status_icon} {status} | {used:.0f}/{limit:.0f} MB "
                f"| {chunks} | {uptime:.1f}% | {last_hb} |"
            )
    else:
        lines.append("*No peers registered. Run `peer/setup.sh` to add a peer node.*")
    lines.append("")

    # ── How to use
    lines.append("## How to Use")
    lines.append("")
    lines.append("### Upload a file")
    lines.append("1. Open a new issue titled `UPLOAD <filename>`")
    lines.append("2. Attach your file in the issue body")
    lines.append("3. The system splits it into chunks and distributes to peers")
    lines.append("")
    lines.append("### Download a file")
    lines.append("1. Open a new issue titled `DOWNLOAD <filename>`")
    lines.append("2. Chunks are fetched from peers and reassembled")
    lines.append("3. The file is delivered as a GitHub Release")
    lines.append("")
    lines.append("### Add a peer")
    lines.append("1. Run `./peer/setup.sh <owner/peer-repo> <owner/tracker-repo>`")
    lines.append("2. Open an issue titled `REGISTER_PEER <owner/peer-repo>`")
    lines.append("")

    # ── Architecture
    lines.append("## Architecture")
    lines.append("")
    lines.append("```")
    lines.append("Issue (UPLOAD/DOWNLOAD)")
    lines.append("  → Tracker workflow (split/collect)")
    lines.append("    → repository_dispatch")
    lines.append("      → Peer workflows (store/fetch)")
    lines.append("        → Chunks as committed .b64 files")
    lines.append("          → GitHub Release (delivery)")
    lines.append("```")
    lines.append("")
    lines.append("Each repo is a seeder. The tracker is a repo. The protocol is `repository_dispatch`.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point: generate and write README.md."""
    content = generate_dashboard()
    readme_path = config.REPO_ROOT / "README.md"
    readme_path.write_text(content)
    print(f"Dashboard written to {readme_path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
