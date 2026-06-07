#!/usr/bin/env python3
"""
E2 test helper: ignores SIGTERM (signal.SIG_IGN) and sleeps 60s.
Used to verify SIGTERM -> SIGKILL escalation actually kills the child.
"""
import signal
import sys
import time

# 关键：忽略 SIGTERM，迫使 SIGKILL 才能杀
signal.signal(signal.SIGTERM, signal.SIG_IGN)

# 写一个 pid file 供测试方验证进程活着
pid = str(__import__("os").getpid())
try:
    with open(sys.argv[1], "w") as f:
        f.write(pid)
except Exception:
    pass

print(json_dummy := '{"alive": true, "pid": ' + pid + '}', flush=True)

# 假装工作：每 2s 打点
for i in range(30):
    time.sleep(2)
    print(f"tick {i}", flush=True)

print('{"ok": true}', flush=True)
