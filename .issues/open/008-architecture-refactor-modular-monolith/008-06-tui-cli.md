# 008-06 TUI 内嵌与 CLI 合并

**Issue ID**: #008-06 | **Priority**: High | **Dependencies**: #008-03 + #008-05

## 目标
合并 `scripts/tradecat_get_*.py` 为 `tradecat` 子命令，TUI 改为 `tradecat tui`。

## 当前 CLI 脚本

```bash
python scripts/tradecat_get_quotes.py NVDA
python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5
python scripts/tradecat_get_news.py --symbol BTCUSDT --limit 5
```

## 新 CLI 命令

```bash
# 行情
tradecat quotes BTCUSDT           # crypto
tradecat quotes --market crypto_spot BTCUSDT ETHUSDT

# 信号
tradecat signals --symbol BTCUSDT --timeframe 1m --limit 5

# 新闻
tradecat news --symbol BTCUSDT --limit 5 --since-minutes 120

# 回测摘要
tradecat backtest-summary --run-id <run_id>

# 虚拟盘
tradecat paper ...

# TUI
tradecat tui
```

## TUI 改造

- [ ] 迁移 `tui-service` 页面到 `tui/pages/`
- [ ] 数据驱动：从 SQLite/process callback 改为 Queue + PG
- [ ] 启动简化为 `tradecat tui` 单命令（不再拉起多个 service 进程）

## 验收标准

- [ ] `tradecat quotes BTCUSDT` 输出 JSON 行情
- [ ] `tradecat signals --symbol BTCUSDT --timeframe 1m` 输出最近信号
- [ ] `tradecat tui` 启动终端看板，显示数据正常
- [ ] 旧 `scripts/tradecat_get_*.py` 脚本已删除
