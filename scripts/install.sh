#!/usr/bin/env bash
# tradeagnt 一键安装（根目录 .venv + pip install -e .）
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo -e "${GREEN}tradeagnt 安装${NC}"
echo "目录: $ROOT"

echo -e "\n${YELLOW}[1/4] 检查 Python...${NC}"
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${RED}需要 python3 3.12+${NC}"
  exit 1
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  Python $PY_VER"

echo -e "\n${YELLOW}[2/4] 创建 .venv...${NC}"
if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
pip install --upgrade pip -q

echo -e "\n${YELLOW}[3/4] 安装 tradeagnt 包...${NC}"
pip install -e ".[dev]" -q
echo "  tradecat CLI 已安装"

echo -e "\n${YELLOW}[4/4] 配置与目录...${NC}"
mkdir -p "$ROOT/data" "$ROOT/run" "$ROOT/logs"
if [[ -f "$ROOT/config/.env.example" && ! -f "$ROOT/config/.env" ]]; then
  cp "$ROOT/config/.env.example" "$ROOT/config/.env"
  chmod 600 "$ROOT/config/.env"
  echo "  已创建 config/.env"
fi

echo -e "\n${GREEN}完成${NC}"
echo "  source .venv/bin/activate"
echo "  TRADECAT_PIPELINE_PROFILE=tui_dual tradecat tui"
echo "  ./scripts/freeze_verify.sh"
