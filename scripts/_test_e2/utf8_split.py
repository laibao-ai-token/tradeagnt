#!/usr/bin/env python3
"""
E2 test helper: print multi-byte UTF-8 split across many small writes.
Verifies StringDecoder reassembles correctly across chunk boundaries.
"""
import sys
import time

# 中文 + emoji (4-byte UTF-8)
# "你好🌏" = e4 bd a0 e5 a5 bd f0 9f 8c 8f
text = "你好🌏TradeCat测试"

# 用 sys.stdout.buffer 写裸字节，强制分多次 write
buf = sys.stdout.buffer
for i, ch in enumerate(text):
    encoded = ch.encode("utf-8")
    # 把多字节字符拆成单字节多次写（最坏情况：3 字节中文拆 3 次）
    for byte in encoded:
        buf.write(bytes([byte]))
        buf.flush()
    # 每个字符后小延迟以确保多次 stdout 事件
    time.sleep(0.005)

# 最后输出一个 JSON 包装
print("", flush=True)
print('{"ok": true, "text": "' + text + '"}', flush=True)
