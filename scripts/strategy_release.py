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
DUAL_BUNDLE = ("fast_1m.yaml", "us_fast_5m.yaml")


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


def _resolve_source_file(src_name: str, *, release_dir: Path | None = None) -> Path | None:
    """Resolve editable source YAML, avoiding copies from the target release folder."""
    release_resolved = release_dir.resolve() if release_dir else None
    src_candidates: list[Path] = [
        STRATEGIES_ROOT / src_name,
        STRATEGIES_ROOT / "current" / src_name,
    ]
    cur = _resolve_current_dir()
    if cur:
        src_candidates.append(cur / src_name)

    seen: set[Path] = set()
    for candidate in src_candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if release_resolved and release_resolved in resolved.parents:
            continue
        return resolved
    return None


def _snapshot_files(
    *,
    files: list[str],
    release_id: str,
    note: str,
    activate: bool,
    force: bool,
) -> int:
    if not files:
        print("error: no strategy files specified", file=sys.stderr)
        return 1

    release_dir = RELEASES_DIR / release_id
    if release_dir.exists() and not force:
        print(f"error: release already exists: {release_id} (use --force)", file=sys.stderr)
        return 1

    release_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    sources: list[str] = []

    for src_name in files:
        src = _resolve_source_file(src_name, release_dir=release_dir)
        if src is None:
            print(f"error: strategy file not found: {src_name}", file=sys.stderr)
            return 1
        dest = release_dir / src.name
        shutil.copy2(src, dest)
        copied.append(src.name)
        rel = src.relative_to(REPO_ROOT) if src.is_relative_to(REPO_ROOT) else str(src)
        sources.append(str(rel))

    manifest = {
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": note.strip(),
        "bundle": len(copied) > 1,
        "source_paths": sources,
        "files": copied,
    }
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if activate:
        _set_current(release_dir)

    rel = release_dir.relative_to(REPO_ROOT)
    print(f"ok: snapshot -> {rel}/ ({', '.join(copied)})")
    if activate:
        print(f"ok: current -> {rel}")
    print(f"load with: current/{copied[0]}  or  releases/{release_id}/{copied[0]}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    files = list(args.file or [])
    if not files:
        files = [args.legacy_file.strip() or DEFAULT_STRATEGY]
    release_id = (args.release_id or "").strip() or _now_release_id()
    return _snapshot_files(
        files=files,
        release_id=release_id,
        note=(args.note or "").strip(),
        activate=bool(args.activate or args.set_current),
        force=bool(args.force),
    )


def cmd_bundle(args: argparse.Namespace) -> int:
    files = list(args.file or list(DUAL_BUNDLE))
    release_id = (args.release_id or "").strip() or _now_release_id()
    note = (args.note or "").strip() or "dual market bundle (crypto + us_stock)"
    return _snapshot_files(
        files=files,
        release_id=release_id,
        note=note,
        activate=bool(args.activate),
        force=bool(args.force),
    )


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
        bundle = " [bundle]" if mf.get("bundle") else ""
        extra = f" | {note}" if note else ""
        print(f"  {d.name}{mark}{bundle}  [{files}]{extra}")
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
    p_snap.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        help="Strategy filename (repeatable; default fast_1m.yaml)",
    )
    p_snap.add_argument("legacy_file", nargs="?", default="", help=argparse.SUPPRESS)
    p_snap.add_argument("-n", "--note", default="", help="Short note stored in manifest.json")
    p_snap.add_argument("--release-id", default="", help="Override folder name (default UTC timestamp)")
    p_snap.add_argument("-a", "--activate", action="store_true", help="Point config/strategies/current to this release")
    p_snap.add_argument("--set-current", action="store_true", help=argparse.SUPPRESS)
    p_snap.add_argument("--force", action="store_true", help="Overwrite existing release folder")
    p_snap.set_defaults(func=cmd_snapshot)

    p_bundle = sub.add_parser("bundle", help=f"Snapshot dual-market pair ({', '.join(DUAL_BUNDLE)})")
    p_bundle.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        help="Override bundle file list",
    )
    p_bundle.add_argument("-n", "--note", default="", help="Note in manifest.json")
    p_bundle.add_argument("--release-id", default="", help="Override release folder name")
    p_bundle.add_argument("-a", "--activate", action="store_true", help="Set current/ to this release")
    p_bundle.add_argument("--force", action="store_true", help="Overwrite existing release folder")
    p_bundle.set_defaults(func=cmd_bundle)

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
