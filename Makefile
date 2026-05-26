# tradeagnt — monolith tradecat package

.PHONY: help init install run verify clean status backtest

help:
	@echo "tradeagnt — standalone terminal assistant"
	@echo ""
	@echo "  make init     - ./scripts/init.sh (root .venv + pip install -e .)"
	@echo "  make install  - ./scripts/install.sh"
	@echo "  make run      - ./scripts/start.sh run (TUI)"
	@echo "  make verify   - ./scripts/verify.sh"
	@echo "  make status   - ./scripts/start.sh status-collector (JSON)"
	@echo "  make backtest - ./scripts/backtest.sh --help"
	@echo "  make clean    - remove caches"

init:
	@./scripts/init.sh

install:
	@./scripts/install.sh

run:
	@./scripts/start.sh run

verify:
	@./scripts/verify.sh

status:
	@./scripts/start.sh status-collector

backtest:
	@./scripts/backtest.sh --help

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf cache/pytest cache/ruff 2>/dev/null || true
	@echo "ok: cache cleaned"
