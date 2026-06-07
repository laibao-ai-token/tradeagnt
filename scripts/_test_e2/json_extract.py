#!/usr/bin/env python3
"""
E2 test helper: print garbage before/after JSON. Used to verify
extractLargestJsonBlock finds the largest valid JSON object.
"""
import sys

# 故意：warn、debug、json、error 顺序
print("WARN: legacy rule ignored", file=sys.stderr)
print("DEBUG: starting up...", flush=True)
print("Loading config from /etc/tradeagnt/...", flush=True)
print('{"ok": true, "tool": "_test_e2/json_extract", "data": {"symbol": "BTC_USDT", "price": 70640.3}}', flush=True)
print("ERROR: trailing log line that should NOT be parsed", file=sys.stderr)
print("DEBUG: shutdown complete", flush=True)
