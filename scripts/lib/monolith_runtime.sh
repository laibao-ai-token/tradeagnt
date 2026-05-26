#!/usr/bin/env bash
# Shared helpers for tradeagnt monolith (root .venv + tradecat CLI / python -m).

monolith_root() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$script_dir/../.." && pwd
}

monolith_python() {
    local root="${1:-$(monolith_root)}"
    if [[ -x "$root/.venv/bin/python" ]]; then
        echo "$root/.venv/bin/python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

monolith_truthy() {
    local value="${1:-}"
    case "${value,,}" in
        1 | true | yes | on) return 0 ;;
        *) return 1 ;;
    esac
}

monolith_bootstrap_pipeline_env() {
    if [[ -z "${TRADECAT_PIPELINE_PROFILE:-}" && -z "${TRADEAGNT_PIPELINE_PROFILE:-}" ]]; then
        export TRADECAT_PIPELINE_PROFILE=tui_dual
    fi
}

monolith_maybe_start_collector() {
    local root="${1:-$(monolith_root)}"
    local start_sh="$root/scripts/start.sh"
    if ! monolith_truthy "${TUI_AUTO_START_COLLECTOR:-0}"; then
        return 0
    fi
    if [[ -x "$start_sh" ]]; then
        /bin/bash "$start_sh" start-collector >/dev/null 2>&1 || true
    fi
}

# Launch via CLI (thin wrapper).
monolith_run_tradecat_tui() {
    local root="${1:-$(monolith_root)}"
    shift || true
    local py
    if ! py="$(monolith_python "$root")"; then
        echo "✗ 未找到 Python：请先运行 ./scripts/init.sh 或 pip install -e ." >&2
        return 1
    fi
    cd "$root" || return 1
    monolith_bootstrap_pipeline_env
    monolith_maybe_start_collector "$root"
    exec "$py" -m tradecat.cli.main tui "$@"
}

# Launch via python -m tradecat.tui (full argparse, run-equity / compat flags).
monolith_run_tui_module() {
    local root="${1:-$(monolith_root)}"
    shift || true
    local py
    if ! py="$(monolith_python "$root")"; then
        echo "✗ 未找到 Python：请先运行 ./scripts/init.sh 或 pip install -e ." >&2
        return 1
    fi
    cd "$root" || return 1
    monolith_bootstrap_pipeline_env
    monolith_maybe_start_collector "$root"
    exec "$py" -m tradecat.tui "$@"
}
