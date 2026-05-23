#!/usr/bin/env bash
# Copy v0.8 Fork-era SQLite into tradeagnt ``data/`` (idempotent).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LEGACY_SIGNAL="$ROOT/libs/database/services/signal-service/signal_history.db"
LEGACY_PAPER="$ROOT/libs/database/services/signal-service/.paper_trading.db"
DATA_DIR="$ROOT/data"
TARGET_SIGNAL="$DATA_DIR/signal_history.db"
TARGET_PAPER="$DATA_DIR/.paper_trading.db"

mkdir -p "$DATA_DIR"

copied=0
if [[ -f "$LEGACY_SIGNAL" && ! -f "$TARGET_SIGNAL" ]]; then
  cp -a "$LEGACY_SIGNAL" "$TARGET_SIGNAL"
  echo "ok: signal_history.db -> data/"
  copied=1
fi
if [[ -f "$LEGACY_PAPER" && ! -f "$TARGET_PAPER" ]]; then
  cp -a "$LEGACY_PAPER" "$TARGET_PAPER"
  echo "ok: .paper_trading.db -> data/"
  copied=1
fi

if [[ "$copied" -eq 0 ]]; then
  if [[ -f "$TARGET_SIGNAL" ]]; then
    echo "skip: data/signal_history.db already exists"
  else
    echo "warn: no legacy DB at libs/.../signal_history.db (fresh install)"
  fi
fi

echo "SIGNAL_DB_PATH=$TARGET_SIGNAL"
echo "Set in config/.env: TRADEAGNT_DATA_DIR=$DATA_DIR"
