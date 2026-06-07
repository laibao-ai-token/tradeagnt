#!/usr/bin/env python3
"""
E2 test helper: print all env vars as JSON. Used to verify env whitelist
that excludes LINEAR_API_KEY / BOT_TOKEN / *_API_KEY / *_SECRET.
"""
import json
import os
import sys

vars_to_check = [
    "LINEAR_API_KEY",
    "BOT_TOKEN",
    "BINANCE_API_KEY",
    "BINANCE_SECRET",
    "DATABASE_URL",
    "HTTP_PROXY",
    "TRADEAGNT_ROOT",
    "TRADEAGNT_AGENT_MODE",
]

visible = {k: os.environ.get(k) for k in vars_to_check}
# also include a few irrelevant to show whitelist is restrictive
visible["_ALL_ENV_KEYS_COUNT"] = str(len(os.environ))

print(json.dumps({"ok": True, "tool": "_test_e2/env", "data": visible}))
