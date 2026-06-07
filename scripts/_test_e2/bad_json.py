#!/usr/bin/env python3
"""
E2 test helper: invalid JSON output.
"""
import sys
print("this is { broken json without closing", flush=True)
sys.exit(0)
