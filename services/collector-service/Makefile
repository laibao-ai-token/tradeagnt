# Collector Service Makefile (minimal)
#
# Targets required by Task 1.2:
# - help
# - venv
# - install
# - clean
# - syntax

SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install clean syntax

help:
	@echo "collector-service targets:"
	@echo ""
	@echo "  make venv    - create virtualenv (.venv)"
	@echo "  make install - install dependencies"
	@echo "  make clean   - remove caches/build artifacts"
	@echo "  make syntax  - py_compile critical modules"

venv:
	@if [ ! -d ".venv" ]; then \
		echo "Creating virtualenv..."; \
		python3 -m venv .venv; \
		$(PIP) install -q --upgrade pip; \
	else \
		echo "Virtualenv already exists"; \
	fi

install: venv
	@echo "Installing dependencies..."
	$(PIP) install -q -r requirements.txt
	$(PIP) install -q -e ../../libs

clean:
	@echo "Cleaning caches..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/

syntax: venv
	$(PYTHON) -m py_compile src/__main__.py src/config.py
	find src -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find src -type f -name "*.pyc" -delete 2>/dev/null || true
