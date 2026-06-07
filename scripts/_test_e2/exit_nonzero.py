#!/usr/bin/env python3
"""
E2 test helper: non-zero exit with stderr message.
Used to verify errorKind='unknown'.
"""
import sys
print("simulated failure", file=sys.stderr, flush=True)
sys.exit(2)
