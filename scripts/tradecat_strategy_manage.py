#!/usr/bin/env python3
"""Bridge: read/write/list/use strategy YAML files.

Actions:
  read    -- Read strategy YAML content
  validate -- Validate strategy YAML without writing
  write   -- Write new strategy YAML (auto-snapshot, auto-validate)
  list    -- List all available strategies
  use     -- Activate a strategy by snapshot, or activate an existing release
  history -- Show version history of a strategy
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
STRATEGIES_ROOT = REPO_ROOT / "config" / "strategies"
CURRENT_LINK = STRATEGIES_ROOT / "current"
RELEASES_DIR = STRATEGIES_ROOT / "releases"
TOOL_NAME = "tradecat_strategy_manage"
YAML_SUFFIXES = {".yaml", ".yml"}


class StrategyPathError(ValueError):
    """Raised when a strategy reference is outside the editable strategy tree."""


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def _base_response() -> dict:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "ts": _utc_now_iso(),
        "request": {},
        "data": None,
        "error": None,
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _safe_strategy_ref(
    name: str,
    *,
    allow_current: bool = True,
    allow_releases: bool = True,
    require_yaml: bool = True,
) -> PurePosixPath:
    """Validate a user-supplied strategy reference before touching the filesystem."""
    raw = (name or "").strip()
    if not raw:
        raise StrategyPathError("Strategy path is empty")
    if "\\" in raw:
        raise StrategyPathError("Strategy path must use POSIX separators")

    ref = PurePosixPath(raw)
    if ref.is_absolute():
        raise StrategyPathError("Absolute strategy paths are not allowed")
    if any(part in ("", ".", "..") for part in ref.parts):
        raise StrategyPathError("Strategy paths may not contain '.' or '..'")
    if require_yaml and ref.suffix not in YAML_SUFFIXES:
        raise StrategyPathError("Strategy path must end with .yaml or .yml")

    first = ref.parts[0]
    if first == "current":
        if not allow_current:
            raise StrategyPathError("current/ is read-only through this tool")
        if len(ref.parts) != 2:
            raise StrategyPathError("current strategy paths must be current/<file>.yaml")
    elif first == "releases":
        if not allow_releases:
            raise StrategyPathError("releases/ is read-only through this tool")
        if len(ref.parts) != 3:
            raise StrategyPathError("release strategy paths must be releases/<release_id>/<file>.yaml")
    elif len(ref.parts) != 1:
        raise StrategyPathError("Strategy paths must be a filename, current/<file>, or releases/<id>/<file>")
    return ref


def _ensure_under_strategies(path: Path) -> Path:
    root = STRATEGIES_ROOT.resolve(strict=False)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise StrategyPathError("Resolved strategy path escapes config/strategies")
    return resolved


def _write_destination(name: str) -> tuple[str, Path]:
    ref = _safe_strategy_ref(name, allow_current=False, allow_releases=False)
    dest = _ensure_under_strategies(STRATEGIES_ROOT / ref.as_posix())
    return ref.as_posix(), dest


def _resolve_strategy(name: str) -> Path | None:
    """Resolve strategy name to an existing YAML file inside config/strategies."""
    ref = _safe_strategy_ref(name)
    rel = Path(*ref.parts)
    candidates: list[Path] = []

    if ref.parts[0] in {"current", "releases"}:
        candidates.append(STRATEGIES_ROOT / rel)
    else:
        candidates.append(STRATEGIES_ROOT / ref.name)
        candidates.append(CURRENT_LINK / ref.name)
        cur = _resolve_current_dir()
        if cur:
            candidates.append(cur / ref.name)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = _ensure_under_strategies(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and resolved.suffix in YAML_SUFFIXES:
            return resolved
    return None


def _resolve_current_dir() -> Path | None:
    if CURRENT_LINK.is_symlink():
        target = CURRENT_LINK.resolve()
        try:
            target = _ensure_under_strategies(target)
        except StrategyPathError:
            return None
        return target if target.is_dir() else None
    if CURRENT_LINK.is_dir():
        try:
            return _ensure_under_strategies(CURRENT_LINK)
        except StrategyPathError:
            return None
    return None


def _validate_yaml(content: str) -> tuple[bool, str]:
    """Validate YAML content against StrategyConfig schema."""
    try:
        import yaml
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return False, "YAML must be a mapping"
        required = ["name", "market", "symbols", "timeframe", "indicators", "rules"]
        missing = [k for k in required if k not in data]
        if missing:
            return False, f"Missing required keys: {', '.join(missing)}"
        # Try Pydantic validation
        from tradecat.core.signals.strategy import StrategyLoader
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            StrategyLoader.load(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _snapshot_strategy(name: str, note: str = "") -> dict:
    """Snapshot a strategy using strategy_release.py."""
    script = REPO_ROOT / "scripts" / "strategy_release.py"
    if not script.is_file():
        return {"ok": False, "error": "strategy_release.py not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(script), "snapshot", "-f", name, "-n", note or f"auto-snapshot before edit"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _release_id_from_current() -> str | None:
    cur = _resolve_current_dir()
    if not cur:
        return None
    releases_root = RELEASES_DIR.resolve(strict=False)
    try:
        rel = cur.relative_to(releases_root)
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def _safe_release_id(raw: str) -> str | None:
    release_id = (raw or "").strip()
    if (
        not release_id
        or "/" in release_id
        or "\\" in release_id
        or release_id in {".", ".."}
        or ".." in release_id
    ):
        return None
    release_dir = _ensure_under_strategies(RELEASES_DIR / release_id)
    return release_id if release_dir.is_dir() else None


def _validate_release_id(raw: str) -> str:
    release_id = (raw or "").strip()
    if (
        not release_id
        or "/" in release_id
        or "\\" in release_id
        or release_id in {".", ".."}
        or ".." in release_id
    ):
        raise StrategyPathError("Invalid release id")
    release_dir = _ensure_under_strategies(RELEASES_DIR / release_id)
    if not release_dir.is_dir():
        raise FileNotFoundError(f"Release not found: {release_id}")
    return release_id


def _release_id_from_strategy_ref(name: str, path: Path) -> str | None:
    ref = _safe_strategy_ref(name)
    if ref.parts[0] == "releases":
        release_id = ref.parts[1]
        release_dir = _ensure_under_strategies(RELEASES_DIR / release_id)
        return release_id if release_dir.is_dir() else None

    releases_root = RELEASES_DIR.resolve(strict=False)
    try:
        rel = path.resolve(strict=False).relative_to(releases_root)
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def _strategy_arg_for_snapshot(path: Path) -> str:
    resolved = _ensure_under_strategies(path)
    rel = resolved.relative_to(STRATEGIES_ROOT.resolve(strict=False))
    return rel.as_posix()


def _activate_release(release_id: str) -> dict:
    script = REPO_ROOT / "scripts" / "strategy_release.py"
    if not script.is_file():
        return {"ok": False, "error": "strategy_release.py not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(script), "use", release_id],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _snapshot_and_activate(strategy_arg: str, note: str = "") -> dict:
    script = REPO_ROOT / "scripts" / "strategy_release.py"
    if not script.is_file():
        return {"ok": False, "error": "strategy_release.py not found"}
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "snapshot",
                "-f",
                strategy_arg,
                "-n",
                note or "activate strategy through trade_strategy_manage",
                "--activate",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "release_id": _release_id_from_current(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _execute_read(args: argparse.Namespace) -> dict:
    response = _base_response()
    name = args.strategy or "current/fast_1m.yaml"
    response["request"] = {"action": "read", "strategy": name}

    try:
        path = _resolve_strategy(name)
    except StrategyPathError as e:
        response["error"] = _error_payload("invalid_strategy_path", str(e))
        return response
    if path is None:
        response["error"] = _error_payload("not_found", f"Strategy not found: {name}")
        return response

    content = path.read_text(encoding="utf-8")
    response["ok"] = True
    response["data"] = {
        "strategy": name,
        "path": _display_path(path),
        "content": content,
        "lines": len(content.splitlines()),
    }
    return response


def _execute_validate(args: argparse.Namespace) -> dict:
    response = _base_response()
    name = args.strategy or ""
    content = args.content or ""
    response["request"] = {"action": "validate", "strategy": name or None}

    if name:
        try:
            _safe_strategy_ref(name, allow_current=True, allow_releases=True)
        except StrategyPathError as e:
            response["error"] = _error_payload("invalid_strategy_path", str(e))
            return response

    if not content:
        if not name:
            response["error"] = _error_payload(
                "invalid_arguments",
                "Either --content or --strategy is required for validate",
            )
            return response
        try:
            path = _resolve_strategy(name)
        except StrategyPathError as e:
            response["error"] = _error_payload("invalid_strategy_path", str(e))
            return response
        if path is None:
            response["error"] = _error_payload("not_found", f"Strategy not found: {name}")
            return response
        content = path.read_text(encoding="utf-8")

    valid, msg = _validate_yaml(content)
    if not valid:
        response["error"] = _error_payload("validation_failed", f"YAML validation failed: {msg}")
        return response

    response["ok"] = True
    response["data"] = {
        "strategy": name or None,
        "valid": True,
        "lines": len(content.splitlines()),
        "dry_run": True,
    }
    return response


def _execute_write(args: argparse.Namespace) -> dict:
    response = _base_response()
    name = args.strategy
    content = args.content
    note = args.note or ""
    dry_run = bool(getattr(args, "dry_run", False))
    response["request"] = {"action": "write", "strategy": name, "note": note, "dry_run": dry_run}

    if not name or not content:
        response["error"] = _error_payload("invalid_arguments", "Both --strategy and --content are required")
        return response

    try:
        safe_name, dest = _write_destination(name)
    except StrategyPathError as e:
        response["error"] = _error_payload("invalid_strategy_path", str(e))
        return response

    # Validate YAML
    valid, msg = _validate_yaml(content)
    if not valid:
        response["error"] = _error_payload("validation_failed", f"YAML validation failed: {msg}")
        return response

    if dry_run:
        response["ok"] = True
        response["data"] = {
            "strategy": safe_name,
            "path": _display_path(dest),
            "lines": len(content.splitlines()),
            "valid": True,
            "written": False,
            "snapshot": False,
            "dry_run": True,
        }
        return response

    # Auto-snapshot existing strategy if overwriting
    existing = dest if dest.is_file() else None
    if existing is not None:
        snap = _snapshot_strategy(safe_name, note or f"auto-snapshot before overwrite by agent")
        if not snap.get("ok"):
            response["error"] = _error_payload("snapshot_failed", f"Failed to snapshot existing strategy: {snap.get('error', snap.get('stderr', ''))}")
            return response

    # Write new strategy
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")

    response["ok"] = True
    response["data"] = {
        "strategy": safe_name,
        "path": _display_path(dest),
        "lines": len(content.splitlines()),
        "snapshot": existing is not None,
        "written": True,
        "dry_run": False,
    }
    return response


def _execute_list(args: argparse.Namespace) -> dict:
    response = _base_response()
    response["request"] = {"action": "list"}

    strategies = []
    cur_dir = _resolve_current_dir()

    # Root level strategies
    for p in sorted(STRATEGIES_ROOT.glob("*.yaml")):
        strategies.append({
            "name": p.name,
            "path": f"strategies/{p.name}",
            "active": False,
        })

    # Current symlink
    if cur_dir:
        for p in sorted(cur_dir.glob("*.yaml")):
            strategies.append({
                "name": f"current/{p.name}",
                "path": f"strategies/current/{p.name}",
                "active": True,
            })

    response["ok"] = True
    response["data"] = {
        "strategies": strategies,
        "count": len(strategies),
        "current": str(cur_dir.relative_to(REPO_ROOT)) if cur_dir else None,
    }
    return response


def _execute_use(args: argparse.Namespace) -> dict:
    response = _base_response()
    name = args.strategy or ""
    release_arg = args.release_id or ""
    note = args.note or ""
    response["request"] = {"action": "use", "strategy": name or None, "release_id": release_arg or None, "note": note}

    if not name and not release_arg:
        response["error"] = _error_payload("invalid_arguments", "Either --strategy or --release-id is required")
        return response
    if name and release_arg:
        response["error"] = _error_payload("invalid_arguments", "Use either --strategy or --release-id, not both")
        return response

    try:
        if release_arg:
            release_id = _validate_release_id(release_arg)
            activation_mode = "release"
            result = _activate_release(release_id)
        else:
            release_id = _safe_release_id(name)
            if release_id is not None:
                activation_mode = "release"
                result = _activate_release(release_id)
            else:
                activation_mode = "snapshot"
                path = _resolve_strategy(name)
                if path is None:
                    response["error"] = _error_payload("not_found", f"Strategy not found: {name}")
                    return response
                release_id = _release_id_from_strategy_ref(name, path)
                if release_id is None:
                    strategy_arg = _strategy_arg_for_snapshot(path)
                    result = _snapshot_and_activate(strategy_arg, note)
                else:
                    activation_mode = "release"
                    result = _activate_release(release_id)
    except StrategyPathError as e:
        response["error"] = _error_payload("invalid_strategy_path", str(e))
        return response
    except FileNotFoundError as e:
        response["error"] = _error_payload("not_found", str(e))
        return response

    if not result.get("ok"):
        response["error"] = _error_payload(
            "use_failed",
            result.get("error") or result.get("stderr") or result.get("stdout") or "activation failed",
            {"stdout": result.get("stdout"), "stderr": result.get("stderr")},
        )
        return response

    response["ok"] = True
    response["data"] = {
        "strategy": name or None,
        "activated": True,
        "activation_mode": activation_mode,
        "release_id": result.get("release_id") or release_id or _release_id_from_current(),
        "current": str(_resolve_current_dir().relative_to(REPO_ROOT)) if _resolve_current_dir() else None,
    }
    return response


def _execute_history(args: argparse.Namespace) -> dict:
    response = _base_response()
    name = args.strategy or "fast_1m.yaml"
    response["request"] = {"action": "history", "strategy": name}

    base_name = Path(name).name
    releases = []

    try:
        _safe_strategy_ref(name)
    except StrategyPathError as e:
        response["error"] = _error_payload("invalid_strategy_path", str(e))
        return response

    if RELEASES_DIR.is_dir():
        for d in sorted(RELEASES_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            files = manifest.get("files", [])
            if base_name in files:
                releases.append({
                    "release_id": d.name,
                    "note": manifest.get("note", ""),
                    "created_at": manifest.get("created_at", ""),
                    "source": manifest.get("source_paths", []),
                })

    response["ok"] = True
    response["data"] = {
        "strategy": name,
        "releases": releases,
        "count": len(releases),
    }
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy management bridge.")
    sub = parser.add_subparsers(dest="action", required=True)

    p_read = sub.add_parser("read", help="Read strategy YAML")
    p_read.add_argument("--strategy", default="current/fast_1m.yaml", help="Strategy name or path")
    p_read.set_defaults(func=_execute_read)

    p_validate = sub.add_parser("validate", help="Validate strategy YAML without writing")
    p_validate.add_argument("--strategy", default="", help="Strategy name or path to validate")
    p_validate.add_argument("--content", default="", help="YAML content to validate")
    p_validate.set_defaults(func=_execute_validate)

    p_write = sub.add_parser("write", help="Write strategy YAML")
    p_write.add_argument("--strategy", required=True, help="Strategy filename (e.g. my_strategy.yaml)")
    p_write.add_argument("--content", required=True, help="YAML content")
    p_write.add_argument("--note", default="", help="Note for version history")
    p_write.add_argument("--dry-run", action="store_true", help="Validate and resolve path without writing")
    p_write.set_defaults(func=_execute_write)

    p_list = sub.add_parser("list", help="List strategies")
    p_list.set_defaults(func=_execute_list)

    p_use = sub.add_parser("use", help="Activate strategy")
    p_use.add_argument("--strategy", default="", help="Strategy name to snapshot and activate")
    p_use.add_argument("--release-id", default="", help="Existing release id to activate")
    p_use.add_argument("--note", default="", help="Note for activation snapshot")
    p_use.set_defaults(func=_execute_use)

    p_history = sub.add_parser("history", help="Version history")
    p_history.add_argument("--strategy", default="fast_1m.yaml", help="Strategy name")
    p_history.set_defaults(func=_execute_history)

    args = parser.parse_args(argv)
    response = args.func(args)
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
