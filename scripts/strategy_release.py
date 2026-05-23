#!/usr/bin/env python3
"""Manage strategy YAML snapshots under config/strategies/releases/<timestamp>/."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_ROOT = REPO_ROOT / "config" / "strategies"
RELEASES_DIR = STRATEGIES_ROOT / "releases"
CURRENT_LINK = STRATEGIES_ROOT / "current"
DEFAULT_STRATEGY = "fast_1m.yaml"


def _now_release_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _read_manifest(release_dir: Path) -> dict:
    path = release_dir / "manifest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_current_dir() -> Path | None:
    if CURRENT_LINK.is_symlink():
        target = CURRENT_LINK.resolve()
        return target if target.is_dir() else None
    if CURRENT_LINK.is_dir():
        return CURRENT_LINK.resolve()
    return None


def cmd_snapshot(args: argparse.Namespace) -> int:
    src_name = args.file.strip() or DEFAULT_STRATEGY
    src_candidates = [
        STRATEGIES_ROOT / "current" / src_name,
        STRATEGIES_ROOT / src_name,
    ]
    cur = _resolve_current_dir()
    if cur:
        src_candidates.insert(0, cur / src_name)

    src: Path | None = None
    for c in src_candidates:
        if c.is_file():
            src = c.resolve()
            break
    if src is None:
        print(f"error: strategy file not found: {src_name}", file=sys.stderr)
        return 1

    release_id = (args.release_id or "").strip() or _now_release_id()
    release_dir = RELEASES_DIR / release_id
    if release_dir.exists() and not args.force:
        print(f"error: release already exists: {release_id} (use --force)", file=sys.stderr)
        return 1

    release_dir.mkdir(parents=True, exist_ok=True)
    dest = release_dir / src_name
    shutil.copy2(src, dest)

    manifest = {
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": (args.note or "").strip(),
        "source_path": str(src.relative_to(REPO_ROOT)) if src.is_relative_to(REPO_ROOT) else str(src),
        "files": [src_name],
    }
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if args.activate or args.set_current:
        _set_current(release_dir)

    rel = release_dir.relative_to(REPO_ROOT)
    print(f"ok: snapshot -> {rel}/{src_name}")
    if args.activate or args.set_current:
        print(f"ok: current -> {rel}")
    print(f"load with: current/{src_name}  or  releases/{release_id}/{src_name}")
    return 0


def _set_current(release_dir: Path) -> None:
    release_dir = release_dir.resolve()
    if CURRENT_LINK.is_symlink() or CURRENT_LINK.is_file():
        CURRENT_LINK.unlink()
    elif CURRENT_LINK.is_dir() and not _resolve_current_dir():
        shutil.rmtree(CURRENT_LINK)
    CURRENT_LINK.symlink_to(release_dir, target_is_directory=True)


def cmd_use(args: argparse.Namespace) -> int:
    release_id = args.release_id.strip()
    release_dir = RELEASES_DIR / release_id
    if not release_dir.is_dir():
        print(f"error: unknown release: {release_id}", file=sys.stderr)
        return 1
    _set_current(release_dir)
    print(f"ok: current -> releases/{release_id}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    cur = _resolve_current_dir()
    cur_id = cur.name if cur and cur.parent == RELEASES_DIR.resolve() else None
    print(f"strategies root: {STRATEGIES_ROOT}")
    print(f"active current: {cur_id or '(none)'}")
    if not RELEASES_DIR.is_dir():
        print("no releases yet")
        return 0
    rows = sorted(p for p in RELEASES_DIR.iterdir() if p.is_dir())
    if not rows:
        print("no releases yet")
        return 0
    for d in rows:
        mark = " *" if d.name == cur_id else ""
        mf = _read_manifest(d)
        note = (mf.get("note") or "").strip()
        files = ", ".join(mf.get("files") or [])
        extra = f" | {note}" if note else ""
        print(f"  {d.name}{mark}  [{files}]{extra}")
    return 0


def cmd_show(_: argparse.Namespace) -> int:
    cur = _resolve_current_dir()
    if not cur:
        print("current: (not set)")
        return 0
    print(f"current: {cur}")
    mf = _read_manifest(cur)
    if mf:
        print(json.dumps(mf, indent=2, ensure_ascii=False))
    for yml in sorted(cur.glob("*.yaml")):
        print(f"  - {yml.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy release folders (timestamp snapshots).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="Copy strategy YAML into releases/<timestamp>/")
    p_snap.add_argument("-f", "--file", default=DEFAULT_STRATEGY, help="Strategy filename")
    p_snap.add_argument("-n", "--note", default="", help="Short note stored in manifest.json")
    p_snap.add_argument("--release-id", default="", help="Override folder name (default UTC timestamp)")
    p_snap.add_argument("-a", "--activate", action="store_true", help="Point config/strategies/current to this release")
    p_snap.add_argument("--set-current", action="store_true", help=argparse.SUPPRESS)
    p_snap.add_argument("--force", action="store_true", help="Overwrite existing release folder")
    p_snap.set_defaults(func=cmd_snapshot)

    p_use = sub.add_parser("use", help="Activate a release (symlink current/)")
    p_use.add_argument("release_id", help="Folder name under releases/")
    p_use.set_defaults(func=cmd_use)

    p_list = sub.add_parser("list", help="List releases")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show active release")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
