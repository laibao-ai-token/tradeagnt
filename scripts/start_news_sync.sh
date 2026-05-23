#!/usr/bin/env bash
# 启动新闻 RSS -> PostgreSQL 同步守护进程（collector-service 不可用时的轻量替代）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/run/news-sync.pid"
LOG_FILE="$ROOT/logs/news-sync.log"
PYTHON="${PYTHON:-python3.12}"

mkdir -p "$ROOT/run" "$ROOT/logs"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "news-sync 已在运行 (PID: $old_pid)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

export TUI_NEWS_RSS_PRESET="${TUI_NEWS_RSS_PRESET:-core}"
export NEWS_RSS_FEEDS="${NEWS_RSS_FEEDS:-}"
# 本地新装的 PG 在 5432；config/.env 若写 5434 会自动回退探测
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/market_data}"
export NEWS_RSS_POLL_INTERVAL_SECONDS="${NEWS_RSS_POLL_INTERVAL_SECONDS:-30}"
export NEWS_RSS_TIMEOUT_SECONDS="${NEWS_RSS_TIMEOUT_SECONDS:-20}"
export NEWS_RSS_LIMIT="${NEWS_RSS_LIMIT:-200}"

nohup "$PYTHON" "$ROOT/scripts/news_sync_daemon.py" >>"$LOG_FILE" 2>&1 &
echo "$!" >"$PID_FILE"
sleep 1
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "news-sync 已启动 (PID: $(cat "$PID_FILE"))"
  echo "  日志: $LOG_FILE"
else
  echo "news-sync 启动失败，查看日志: $LOG_FILE" >&2
  tail -n 20 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi
