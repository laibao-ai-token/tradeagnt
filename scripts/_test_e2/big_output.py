#!/usr/bin/env python3
"""
E2 test helper: print ~10MB of JSON data. Used to verify 8MB stdout cap
truncates and marks the result.
"""
import sys

# 8 MB = 8 * 1024 * 1024 = 8388608 bytes
# 我们输出 10 MB 确保截断
size_mb = 10
chunk = "A" * (1024 * 1024)  # 1MB

print('{"ok": true, "tool": "_test_e2/big", "data": "', end="", flush=True)
for _ in range(size_mb):
    sys.stdout.write(chunk)
    sys.stdout.flush()
print('"}', flush=True)
