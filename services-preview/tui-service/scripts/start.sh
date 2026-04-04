#!/usr/bin/env bash
# tui-service 启动脚本（预览）

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$(dirname "$SERVICE_DIR")")"
source "$REPO_ROOT/scripts/lib/db_url.sh"

# NOTE: tui-service does not require config/.env.
# Do NOT source it here, because template values may include spaces/parentheses and break bash parsing.
# If specific optional keys are needed, read them via tc_read_env_key (Python parser) instead.

_export_env_key_if_missing() {
  local key="$1"
  local value="${!key:-}"
  if [[ -n "$value" ]]; then
    return 0
  fi

  value="$(tc_read_env_key "$REPO_ROOT/config/.env" "$key" || true)"
  if [[ -n "${value:-}" ]]; then
    export "$key=$value"
  fi
}

for _proxy_key in HTTP_PROXY HTTPS_PROXY NO_PROXY; do
  _export_env_key_if_missing "$_proxy_key"
done

if [[ -n "${HTTP_PROXY:-}" && -z "${http_proxy:-}" ]]; then
  export http_proxy="$HTTP_PROXY"
fi
if [[ -n "${HTTPS_PROXY:-}" && -z "${https_proxy:-}" ]]; then
  export https_proxy="$HTTPS_PROXY"
fi
if [[ -n "${NO_PROXY:-}" && -z "${no_proxy:-}" ]]; then
  export no_proxy="$NO_PROXY"
fi

for _news_preset_key in TUI_NEWS_RSS_PRESET NEWS_RSS_PRESET; do
  _export_env_key_if_missing "$_news_preset_key"
done

# Optional: allow configuring RSS feeds in config/.env (without sourcing it).
if [[ -z "${TUI_NEWS_RSS_FEEDS:-}" && -z "${NEWS_RSS_FEEDS:-}" ]]; then
  _rss_from_env="$(tc_read_env_key "$REPO_ROOT/config/.env" "TUI_NEWS_RSS_FEEDS" || true)"
  if [[ -n "${_rss_from_env:-}" ]]; then
    export TUI_NEWS_RSS_FEEDS="$_rss_from_env"
  else
    _rss_from_env="$(tc_read_env_key "$REPO_ROOT/config/.env" "NEWS_RSS_FEEDS" || true)"
    if [[ -n "${_rss_from_env:-}" ]]; then
      export NEWS_RSS_FEEDS="$_rss_from_env"
    fi
  fi
fi

_python_is_compatible() {
  local py="$1"
  "$py" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

_pick_python() {
  local -a candidates=(
    "python3.12"
    "python3.11"
    "/root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11"
    "python3.10"
    "python3"
  )

  local candidate=""
  local resolved=""
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    [[ -z "$resolved" ]] && continue
    if _python_is_compatible "$resolved"; then
      echo "$resolved"
      return 0
    fi
  done
  return 1
}

_requirements_has_packages() {
  local req_file="$1"
  [[ -f "$req_file" ]] || return 1
  grep -Eq '^[[:space:]]*[^#[:space:]]' "$req_file"
}

VENV_DIR="$SERVICE_DIR/.venv"
if [[ -x "$VENV_DIR/bin/python" ]] && ! _python_is_compatible "$VENV_DIR/bin/python"; then
  VENV_DIR="$SERVICE_DIR/.venv-py310plus"
fi

if [[ ! -d "$VENV_DIR" || ! -x "$VENV_DIR/bin/python" ]]; then
  COMPATIBLE_PY="$(_pick_python || true)"
  if [[ -z "${COMPATIBLE_PY:-}" ]]; then
    echo "✗ 未找到兼容的 Python 解释器（需要 3.10+）"
    echo "  当前系统 python3: $(python3 --version 2>/dev/null || echo 'not found')"
    echo "  请先安装 Python 3.11/3.12，或手动指定兼容解释器创建 $VENV_DIR"
    exit 1
  fi

  echo "创建虚拟环境... ($COMPATIBLE_PY)"
  "$COMPATIBLE_PY" -m venv "$VENV_DIR"

  if _requirements_has_packages "$SERVICE_DIR/requirements.txt"; then
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV_DIR/bin/pip" install -q -r "$SERVICE_DIR/requirements.txt"
  fi
fi

PYTHON="$VENV_DIR/bin/python"
if ! _python_is_compatible "$PYTHON"; then
  echo "✗ TUI 虚拟环境 Python 版本过低: $("$PYTHON" --version 2>/dev/null || echo 'unknown')"
  echo "  请删除不兼容环境后重试: rm -rf $VENV_DIR"
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/libs:$SERVICE_DIR${PYTHONPATH:+:$PYTHONPATH}"

_ensure_common_package() {
  if "$PYTHON" - <<'PY' >/dev/null 2>&1
import common.scheduler
PY
  then
    return 0
  fi

  echo "检测到缺少 shared common 包，正在安装..."
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV_DIR/bin/pip" install -q --no-build-isolation -e "$REPO_ROOT/libs"
}

_ensure_common_package

SIGNAL_START_SCRIPT="$REPO_ROOT/services/signal-service/scripts/start.sh"
SIGNAL_PID_FILE="$REPO_ROOT/services/signal-service/logs/signal-service.pid"
COLLECTOR_SERVICE_DIR="$REPO_ROOT/services/collector-service"
COLLECTOR_PID_FILE="$REPO_ROOT/run/tui-collector.pid"
COLLECTOR_SHARED_PID_FILE="$REPO_ROOT/run/collector-service.pid"
COLLECTOR_LOG_FILE="$REPO_ROOT/logs/tui-collector.log"

# 轻量节点默认自动拉起 collector-service（crypto）；signal-service 仍默认关闭，可用 TUI_AUTO_START_*=1 显式开启。
AUTO_START_SIGNAL="${TUI_AUTO_START_SIGNAL:-0}"
AUTO_START_COLLECTOR="${TUI_AUTO_START_COLLECTOR:-1}"

# 默认退出 TUI 后 1 小时再停止由 TUI 启动的服务。
SIGNAL_STOP_DELAY_SECONDS="${TUI_SIGNAL_STOP_DELAY_SECONDS:-3600}"
COLLECTOR_STOP_DELAY_SECONDS="${TUI_COLLECTOR_STOP_DELAY_SECONDS:-3600}"

# 仅在本脚本启动该服务时置为 1，退出 TUI 时才会自动 stop。
SIGNAL_STARTED_BY_TUI=0
COLLECTOR_STARTED_BY_TUI=0

if ! [[ "$SIGNAL_STOP_DELAY_SECONDS" =~ ^[0-9]+$ ]]; then
  SIGNAL_STOP_DELAY_SECONDS=3600
fi
if ! [[ "$COLLECTOR_STOP_DELAY_SECONDS" =~ ^[0-9]+$ ]]; then
  COLLECTOR_STOP_DELAY_SECONDS=3600
fi

_schedule_delayed_stop() {
  local managed_pid="$1"
  local delay="$2"
  local pid_file="$3"
  local start_script="$4"
  local stop_mode="${5:-script}"

  TUI_DELAY_MANAGED_PID="$managed_pid" \
  TUI_DELAY_SECONDS="$delay" \
  TUI_DELAY_PID_FILE="$pid_file" \
  TUI_DELAY_START_SCRIPT="$start_script" \
  TUI_DELAY_STOP_MODE="$stop_mode" \
  nohup /bin/bash -lc '
    sleep "${TUI_DELAY_SECONDS}"
    if [[ -f "${TUI_DELAY_PID_FILE}" ]] && [[ "$(cat "${TUI_DELAY_PID_FILE}" 2>/dev/null || true)" == "${TUI_DELAY_MANAGED_PID}" ]]; then
      if [[ "${TUI_DELAY_STOP_MODE}" == "kill" ]]; then
        kill "${TUI_DELAY_MANAGED_PID}" >/dev/null 2>&1 || true
        rm -f "${TUI_DELAY_PID_FILE}"
      else
        "${TUI_DELAY_START_SCRIPT}" stop >/dev/null 2>&1 || true
      fi
    fi
  ' >/dev/null 2>&1 &
}

_start_signal_for_tui() {
  if [[ "$AUTO_START_SIGNAL" != "1" ]]; then
    return 0
  fi

  if [[ ! -x "$SIGNAL_START_SCRIPT" ]]; then
    echo "⚠️ 未找到 signal-service 启动脚本: $SIGNAL_START_SCRIPT"
    echo "   将继续启动 TUI（仅行情/历史视图可用）"
    return 0
  fi

  if "$SIGNAL_START_SCRIPT" status >/dev/null 2>&1; then
    echo "✓ signal-service 已运行（TUI 复用现有进程）"
    return 0
  fi

  echo "启动 signal-service（随 TUI 一并启动）..."
  if "$SIGNAL_START_SCRIPT" start; then
    SIGNAL_STARTED_BY_TUI=1
  else
    echo "⚠️ signal-service 启动失败，继续进入 TUI（仅行情/历史视图可用）"
  fi
}

_collector_python() {
  local py="$COLLECTOR_SERVICE_DIR/.venv/bin/python"
  if [[ -x "$py" ]]; then
    echo "$py"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

_pid_is_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid=""
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

_start_collector_for_tui() {
  if [[ "$AUTO_START_COLLECTOR" != "1" ]]; then
    return 0
  fi

  if [[ ! -d "$COLLECTOR_SERVICE_DIR" ]]; then
    echo "⚠️ 未找到 collector-service 目录: $COLLECTOR_SERVICE_DIR"
    echo "   将继续启动 TUI（仅行情/历史视图可用）"
    return 0
  fi

  if _pid_is_running "$COLLECTOR_SHARED_PID_FILE"; then
    echo "✓ collector-service 已运行（TUI 复用现有进程）"
    return 0
  fi

  if _pid_is_running "$COLLECTOR_PID_FILE"; then
    echo "✓ collector-service 已运行（TUI 复用本地轻量进程）"
    return 0
  fi

  local collector_py=""
  if ! collector_py="$(_collector_python)"; then
    echo "⚠️ 未找到可用 Python，无法自动启动 collector-service"
    echo "   将继续启动 TUI（行情仍可直接抓取）"
    return 0
  fi

  mkdir -p "$(dirname "$COLLECTOR_PID_FILE")" "$(dirname "$COLLECTOR_LOG_FILE")"

  echo "启动 collector-service（随 TUI 一并启动，默认只拉起 crypto）..."
  (
    export COLLECTOR_CRYPTO_KLINE_ENABLED=1
    export COLLECTOR_CRYPTO_METRICS_ENABLED=1
    cd "$COLLECTOR_SERVICE_DIR"
    PYTHONPATH="../../libs${PYTHONPATH:+:$PYTHONPATH}" "$collector_py" -m src --run --only=crypto >> "$COLLECTOR_LOG_FILE" 2>&1
  ) &
  local pid=$!
  echo "$pid" > "$COLLECTOR_PID_FILE"

  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    COLLECTOR_STARTED_BY_TUI=1
  else
    rm -f "$COLLECTOR_PID_FILE"
    echo "⚠️ collector-service 启动失败，继续进入 TUI（行情仍可直接抓取）"
  fi
}

_stop_signal_if_needed() {
  if [[ "${SIGNAL_STARTED_BY_TUI:-0}" != "1" ]]; then
    return 0
  fi

  if [[ "${TUI_KEEP_SIGNAL_ON_EXIT:-0}" == "1" ]]; then
    echo "保留 signal-service 运行中（TUI_KEEP_SIGNAL_ON_EXIT=1）"
    return 0
  fi

  if [[ "$SIGNAL_STOP_DELAY_SECONDS" == "0" ]]; then
    echo "停止 signal-service（由 TUI 启动）..."
    "$SIGNAL_START_SCRIPT" stop >/dev/null 2>&1 || true
    return 0
  fi

  local managed_pid=""
  if [[ -f "$SIGNAL_PID_FILE" ]]; then
    managed_pid="$(cat "$SIGNAL_PID_FILE" 2>/dev/null || true)"
  fi

  if [[ -z "$managed_pid" ]]; then
    echo "停止 signal-service（由 TUI 启动）..."
    "$SIGNAL_START_SCRIPT" stop >/dev/null 2>&1 || true
    return 0
  fi

  echo "已安排 ${SIGNAL_STOP_DELAY_SECONDS}s 后停止 signal-service（可用 TUI_SIGNAL_STOP_DELAY_SECONDS=0 立即停止）"
  _schedule_delayed_stop "$managed_pid" "$SIGNAL_STOP_DELAY_SECONDS" "$SIGNAL_PID_FILE" "$SIGNAL_START_SCRIPT"
}

_stop_collector_if_needed() {
  if [[ "${COLLECTOR_STARTED_BY_TUI:-0}" != "1" ]]; then
    return 0
  fi

  if [[ "${TUI_KEEP_COLLECTOR_ON_EXIT:-0}" == "1" ]]; then
    echo "保留 collector-service 运行中（TUI_KEEP_COLLECTOR_ON_EXIT=1）"
    return 0
  fi

  if [[ "$COLLECTOR_STOP_DELAY_SECONDS" == "0" ]]; then
    echo "停止 collector-service（由 TUI 启动）..."
    if _pid_is_running "$COLLECTOR_PID_FILE"; then
      kill "$(cat "$COLLECTOR_PID_FILE")" >/dev/null 2>&1 || true
    fi
    rm -f "$COLLECTOR_PID_FILE"
    return 0
  fi

  local managed_pid=""
  if [[ -f "$COLLECTOR_PID_FILE" ]]; then
    managed_pid="$(cat "$COLLECTOR_PID_FILE" 2>/dev/null || true)"
  fi

  if [[ -z "$managed_pid" ]]; then
    echo "停止 collector-service（由 TUI 启动）..."
    rm -f "$COLLECTOR_PID_FILE"
    return 0
  fi

  echo "已安排 ${COLLECTOR_STOP_DELAY_SECONDS}s 后停止 collector-service（可用 TUI_COLLECTOR_STOP_DELAY_SECONDS=0 立即停止）"
  _schedule_delayed_stop "$managed_pid" "$COLLECTOR_STOP_DELAY_SECONDS" "$COLLECTOR_PID_FILE" "/bin/kill" "kill"
}

_stop_existing_tui_instances() {
  local pattern="$PYTHON -m src"
  local -a pids=()
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && pids+=("$pid")
  done < <(pgrep -f "$pattern" || true)

  if [[ ${#pids[@]} -eq 0 ]]; then
    return 0
  fi

  echo "检测到已有 TUI 实例: ${pids[*]}，正在停止旧实例..."
  kill "${pids[@]}" >/dev/null 2>&1 || true

  for _ in $(seq 1 20); do
    local alive=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        alive=1
        break
      fi
    done
    if [[ "$alive" == "0" ]]; then
      break
    fi
    sleep 0.1
  done

  local -a remain=()
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      remain+=("$pid")
    fi
  done

  if [[ ${#remain[@]} -gt 0 ]]; then
    echo "旧实例未完全退出，强制停止: ${remain[*]}"
    kill -9 "${remain[@]}" >/dev/null 2>&1 || true
  fi
}

run() {
  # NOTE: curses TUI must run in the foreground attached to a real TTY.
  if [[ ! -t 0 || ! -t 1 ]]; then
    echo "✗ 当前会话不是交互式 TTY，无法显示 TUI（curses 需要真实终端）"
    echo "  请在本地终端或 ssh -t 会话中运行。"
    echo "  示例: ./scripts/start.sh run --view market_micro --micro-symbol BTC_USDT --micro-interval 5"
    return 2
  fi
  if [[ -z "${TERM:-}" || "${TERM:-}" == "dumb" ]]; then
    echo "⚠️ TERM 未设置或为 dumb，建议先执行: export TERM=xterm-256color"
  fi

  cd "$SERVICE_DIR"

  local singleton="${TUI_SINGLETON:-1}"
  if [[ "$singleton" != "0" && "$singleton" != "1" ]]; then
    singleton="1"
  fi
  if [[ "$singleton" == "1" ]]; then
    _stop_existing_tui_instances
  fi

  _start_collector_for_tui
  _start_signal_for_tui

  local hot_reload="${TUI_HOT_RELOAD:-0}"
  if [[ "$hot_reload" != "0" && "$hot_reload" != "1" ]]; then
    hot_reload="0"
  fi

  local poll="${TUI_HOT_RELOAD_POLL:-1.0}"
  if ! [[ "$poll" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    poll="1.0"
  fi

  local -a tui_args=()
  if [[ "$hot_reload" == "1" ]]; then
    tui_args+=(--hot-reload --hot-reload-poll "$poll")
  fi

  set +e
  "$PYTHON" -m src "${tui_args[@]}" "$@"
  local rc=$?
  set -e

  _stop_signal_if_needed
  _stop_collector_if_needed
  return "$rc"
}

run_dev() {
  local poll="${TUI_HOT_RELOAD_POLL:-1.0}"
  if ! [[ "$poll" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    poll="1.0"
  fi
  echo "开发模式: 已启用 TUI 热重载（监听 services-preview/tui-service/src/*.py, poll=${poll}s）"
  TUI_HOT_RELOAD=1 TUI_HOT_RELOAD_POLL="$poll" run "$@"
}

run_news() {
  local sleep_s="${NEWS_RSS_POLL_INTERVAL_SECONDS:-2}"
  if [[ $# -gt 0 && ! "${1:-}" =~ ^- ]]; then
    sleep_s="$1"
    shift
  fi

  local detach="0"
  if [[ $# -gt 0 && "${1:-}" =~ ^[01]$ ]]; then
    detach="$1"
    shift
  fi

  local news_log_dir="$REPO_ROOT/logs"
  local news_log_file="$news_log_dir/collector-news.log"

  local collector_py
  if ! collector_py="$(_collector_python)"; then
    echo "❌ collector-service 未初始化（缺少 $COLLECTOR_SERVICE_DIR/.venv/bin/python）"
    echo "   先执行: ./scripts/init.sh collector-service"
    return 1
  fi

  mkdir -p "$news_log_dir"
  echo "启动 7x24 新闻采集: sleep=${sleep_s}s"
  (
    export COLLECTOR_NEWS_ENABLED=1
    export COLLECTOR_NEWS_RSS_POLL_INTERVAL_SECONDS="$sleep_s"
    cd "$COLLECTOR_SERVICE_DIR"
    exec "$collector_py" -m src --run --only=news >> "$news_log_file" 2>&1 < /dev/null
  ) &
  local pid=$!

  if [[ "$detach" != "1" ]]; then
    # Expand the child pid now; local variables are gone by the time the EXIT trap fires.
    trap "kill '$pid' 2>/dev/null || true" EXIT INT TERM
  else
    echo "新闻采集进程已后台运行 (PID: $pid)；退出 TUI 不会停止采集。"
  fi

  run --view market_news "$@"
}

run_equity() {
  # Run a collector-service equity poll in background, then run the TUI in foreground.
  # This keeps TUI stdlib-only while still providing "one-command collection + view".
  local market="${1:-us_stock}"
  local provider="${2:-nasdaq}"
  local symbols="${3:-NVDA}"
  local sleep_s="${4:-60}"
  local limit="${5:-5}"
  local detach="${6:-0}"

  local collector_py
  if ! collector_py="$(_collector_python)"; then
    echo "❌ collector-service 未初始化（缺少 $COLLECTOR_SERVICE_DIR/.venv/bin/python）"
    echo "   先执行: ./scripts/init.sh collector-service"
    return 1
  fi

  local collector_market=""
  local provider_var=""
  local symbols_var=""
  case "$market" in
    us|us_stock)
      collector_market="us"
      provider_var="COLLECTOR_EQUITY_US_PROVIDER"
      symbols_var="COLLECTOR_EQUITY_US_SYMBOLS"
      ;;
    cn|cn_stock)
      collector_market="cn"
      provider_var="COLLECTOR_EQUITY_CN_PROVIDER"
      symbols_var="COLLECTOR_EQUITY_CN_SYMBOLS"
      ;;
    hk|hk_stock)
      collector_market="hk"
      provider_var="COLLECTOR_EQUITY_HK_PROVIDER"
      symbols_var="COLLECTOR_EQUITY_HK_SYMBOLS"
      ;;
    *)
      echo "❌ 不支持的市场: $market（可选: us_stock/cn_stock/hk_stock）"
      return 1
      ;;
  esac

  echo "启动采集: market=$market provider=$provider symbols=$symbols sleep=$sleep_s limit=$limit"
  (
    export COLLECTOR_EQUITY_ENABLED=1
    export COLLECTOR_EQUITY_MARKETS="$collector_market"
    export COLLECTOR_EQUITY_POLL_INTERVAL_SECONDS="$sleep_s"
    export COLLECTOR_EQUITY_LIMIT="$limit"
    export "$provider_var=$provider"
    export "$symbols_var=$symbols"
    cd "$COLLECTOR_SERVICE_DIR"
    exec "$collector_py" -m src --run --only=equity
  ) &
  local pid=$!

  if [[ "$detach" != "1" ]]; then
    # Expand the child pid now; local variables are gone by the time the EXIT trap fires.
    trap "kill '$pid' 2>/dev/null || true" EXIT INT TERM
  else
    echo "采集进程已后台运行 (PID: $pid)；退出 TUI 不会停止采集。"
  fi

  # Show a watchlist for all provided symbols by default.
  run --quote-symbols "$symbols" --quote-market "$market"
}


start() { shift || true; run "$@"; }

stop() {
  echo "tui-service 是交互式 TUI，需要前台运行。停止请使用 Ctrl+C。"
}

status() {
  echo "tui-service 是交互式 TUI，无后台状态。请直接运行: ./scripts/start.sh run（默认单实例 + 轻量模式）"

  if [[ "$AUTO_START_COLLECTOR" == "1" ]]; then
    echo "默认行为：run/start 会自动尝试启动 collector-service（crypto， 可用 TUI_AUTO_START_COLLECTOR=0 关闭）"
    echo "默认行为：退出 TUI 后 ${COLLECTOR_STOP_DELAY_SECONDS}s 自动停止由 TUI 启动的 collector-service"
  else
    echo "当前行为：不自动启动 collector-service（可用 TUI_AUTO_START_COLLECTOR=1 开启）"
  fi

  if [[ "$AUTO_START_SIGNAL" == "1" ]]; then
    echo "当前行为：run/start 会自动尝试启动 signal-service（可用 TUI_AUTO_START_SIGNAL=0 关闭）"
    echo "默认行为：退出 TUI 后 ${SIGNAL_STOP_DELAY_SECONDS}s 自动停止由 TUI 启动的 signal-service"
  else
    echo "默认行为：不自动启动 signal-service（可用 TUI_AUTO_START_SIGNAL=1 开启）"
  fi
}

case "${1:-status}" in
  run) shift; run "$@" ;;
  run-dev) shift; run_dev "$@" ;;
  run-equity) shift; run_equity "$@" ;;
  run-news) shift; run_news "$@" ;;
  start) start "$@" ;;
  stop) stop ;;
  status) status ;;
  restart) stop; sleep 1; start ;;
  *)
    echo "用法: $0 {run|run-dev|run-equity|run-news|start|stop|status|restart}"
    echo ""
    echo "环境变量："
    echo "  TUI_AUTO_START_COLLECTOR=0   禁用 run/start 自动启动 collector-service"
    echo "  TUI_COLLECTOR_STOP_DELAY_SECONDS=3600  退出 TUI 后延迟停止 collector-service（默认 1h）"
    echo "  TUI_KEEP_COLLECTOR_ON_EXIT=1 退出 TUI 时保留自动启动的 collector-service"
    echo "  TUI_AUTO_START_SIGNAL=1      为 run/start 自动启动 signal-service"
    echo "  TUI_SIGNAL_STOP_DELAY_SECONDS=3600  退出 TUI 后延迟停止 signal-service（默认 1h）"
    echo "  TUI_KEEP_SIGNAL_ON_EXIT=1    退出 TUI 时保留自动启动的 signal-service"
    echo "  TUI_SINGLETON=0              允许多开 TUI（默认单实例）"
    echo "  TUI_HOT_RELOAD=1             为 run/start 开启热重载（默认关闭）"
    echo "  TUI_HOT_RELOAD_POLL=1.0      run/run-dev 热重载轮询间隔（秒）"
    echo ""
    echo "示例:"
    echo "  $0 run                  # 默认轻量模式（refresh=2s / quote=3s）"
    echo "  $0 run-dev"
    echo "  TUI_SINGLETON=0 $0 run  # 允许多开实例"
    echo "  TUI_HOT_RELOAD=1 $0 run # 显式开启热重载"
    echo "  TUI_AUTO_START_SIGNAL=1 $0 run"
    echo "  TUI_AUTO_START_COLLECTOR=0 $0 run"
    echo "  TUI_COLLECTOR_STOP_DELAY_SECONDS=0 TUI_SIGNAL_STOP_DELAY_SECONDS=0 $0 run"
    echo "  $0 run-equity us_stock nasdaq NVDA 60 5"
    echo "  $0 run-equity hk_stock eastmoney 1810.HK 60 5"
    echo "  $0 run-news 2"
    exit 1
    ;;
esac
