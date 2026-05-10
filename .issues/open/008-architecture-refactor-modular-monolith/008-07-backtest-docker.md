# 008-07 回测保留 + Docker + CI 修复

**Issue ID**: #008-07 | **Priority**: High | **Dependencies**: 全部前置完成

## 目标
保留全部 5 种回测模式，补齐 Docker 和 CI。

## 保留的回测模式

1. **default** — 前向后测（读取 signal_history）
2. **offline_replay** — 离线回放（基于 K 线模拟信号）
3. **offline_rule_replay** — 129 规则离线重放
4. **compare_history_rule** — 历史信号 vs 规则对比
5. **walk_forward** — 滚动窗口验证

## 任务清单

### 回测迁移
- [ ] `backtest/runner.py` — 主回测引擎
- [ ] `backtest/walkforward.py` — Walk-Forward
- [ ] `backtest/offline_replay.py` — 离线回放
- [ ] `backtest/rule_replay.py` — 规则重放
- [ ] `backtest/comparison.py` — 对比报告
- [ ] 回测从读取 SQLite `signal_history.db` → 读取 PG `signal.history`

### Docker
- [ ] `Dockerfile` — Python 3.12 slim, 安装 TimescaleDB 客户端
- [ ] `docker-compose.yml` — tradecat + TimescaleDB 服务
- [ ] `.dockerignore`

### CI 修复
- [ ] `tests/` 目录 + 真实 pytest（替换占位测试）
- [ ] `.github/workflows/ci.yml` 或 `Makefile test`
- [ ] `python -m pytest` 通过

### 文档
- [ ] `README.md` 重写 — 新架构快速开始
- [ ] `README_EN.md` 同步更新

## 验收标准

- [ ] `./scripts/backtest.sh` 仍然工作（兼容层或转发）
- [ ] `docker-compose up --build` 成功启动
- [ ] `tradecat backtest --config default.yaml --mode offline_replay` 输出报告
- [ ] `pytest` 通过率 > 80%
- [ ] 5 种回测模式全部可用
