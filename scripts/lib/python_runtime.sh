#!/usr/bin/env bash
# 统一 Python 运行时选择与版本检测工具。

TC_MIN_PYTHON_MAJOR=3
TC_MIN_PYTHON_MINOR=12

tc_python_is_compatible() {
    local py_bin="$1"
    [[ -n "$py_bin" ]] || return 1
    "$py_bin" - <<'PY' >/dev/null 2>&1
import sys

raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
}

tc_python_version_string() {
    local py_bin="$1"
    [[ -n "$py_bin" ]] || return 1
    "$py_bin" - <<'PY'
import sys

sys.stdout.write(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
}

tc_pick_python() {
    local -a candidates=()
    if [[ -n "${TRADECAT_PYTHON:-}" ]]; then
        candidates+=("${TRADECAT_PYTHON}")
    fi
    candidates+=(
        "python3.13"
        "python3.12"
        "python3"
        "python"
    )

    local candidate=""
    local resolved=""
    local -A seen=()
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            resolved="$candidate"
        else
            resolved="$(command -v "$candidate" 2>/dev/null || true)"
        fi
        [[ -n "$resolved" ]] || continue
        if [[ -n "${seen[$resolved]:-}" ]]; then
            continue
        fi
        seen["$resolved"]=1
        if tc_python_is_compatible "$resolved"; then
            echo "$resolved"
            return 0
        fi
    done

    return 1
}
