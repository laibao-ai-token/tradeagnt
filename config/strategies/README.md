# 策略目录说明

> **新市场接入原则与清单**：见 [docs/market-integration/README.md](../../docs/market-integration/README.md)

## 目录结构

- `current/` → 指向当前生效的版本（符号链接）
- `releases/<YYYYMMDD_HHMMSS>/` → 每次快照（时间戳文件夹）
  - `fast_1m.yaml`（或其它策略文件）
  - `manifest.json`（备注、创建时间）
- 根目录下的 `*.yaml` → 兼容旧命令，建议改 `current/` 里的文件

## 常用命令

```bash
# 改完 current/fast_1m.yaml 后打快照（并设为当前）
python3 scripts/strategy_release.py snapshot -n "调 RSI 阈值" --activate

# 列出所有版本
python3 scripts/strategy_release.py list

# 回滚到某一版
python3 scripts/strategy_release.py use 20260519_165311

# 查看当前指向
python3 scripts/strategy_release.py show
```

## 加载方式

`tradecat daemon`、`TUI` 默认使用 `current/fast_1m.yaml`。  
也可显式指定：`--strategy releases/20260519_165311/fast_1m.yaml`  
环境变量：`TUI_SIGNAL_STRATEGY=current/fast_1m.yaml`

## 美股 Demo（对齐 crypto 口径）

| 文件 | 说明 |
|:---|:---|
| `us_fast_5m.yaml` | 美股 RSI 5m 策略（NVDA/META/ORCL） |

```bash
# 信号扫描
tradecat signal --config us_fast_5m.yaml --symbol NVDA

# 守护进程 + 模拟盘自动交易（USD 名义）
tradecat daemon --strategy us_fast_5m.yaml --auto-trade --notional 500

# 回测（当日/近几日 intraday，scan 全历史 bar）
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 3

# 模拟盘手动开仓
tradecat paper long NVDA --notional 1000 --price 120.5 --market us_stock

# TUI 仅美股策略
TUI_SIGNAL_STRATEGY=us_fast_5m.yaml PAPER_AUTO_MARKET=us_stock tradecat tui

# TUI 加密 + 美股双策略（P2 用 1/2 切换加密/美股模拟视图）
TUI_SIGNAL_STRATEGY=current/fast_1m.yaml \
TUI_SIGNAL_STRATEGY_EXTRA=us_fast_5m.yaml \
PAPER_AUTO_MARKET=all \
tradecat tui
```

## 归档记录（示例）

| release_id | 说明 |
|:---|:---|
| `20260519_165311` | 初版 Paper RSI 5m baseline |
| `20260521_114912` | 42h daemon 实盘归档（20260520–21，峰值回撤约 3%） |
