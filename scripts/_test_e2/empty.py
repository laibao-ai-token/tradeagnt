#!/usr/bin/env python3
"""
E2 test helper: empty stdout (just stderr).
Used to verify errorKind='empty' when exit code is 0 but no JSON.
"""
import sys
print("this is just a log line on stderr", file=sys.stderr, flush=True)
# 不输出任何 stdout
