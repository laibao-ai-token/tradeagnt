# CLI 与运行时

统一入口：`tradecat`（`src/tradecat/cli/main.py`）

## 与市场相关的命令

| 命令 | market 来源 | Provider 默认 |
|:---|:---|:---|
| `tradecat signal -c <yaml> -s <sym>` | 策略 YAML | `default_provider_for_market` |
| `tradecat daemon --strategy <yaml>` | 策略 YAML | 同上 |
| `tradecat backtest --strategy <yaml> -s <sym>` | 策略 YAML | 同上 |
| `tradecat paper long <sym> --market <m>` | CLI `--market` | N/A（用现价参数） |

`--provider` 可覆盖默认值（如 `--provider us_equity`）。

## daemon

```bash
# crypto（默认策略）
tradecat daemon --strategy current/fast_1m.yaml --symbols BTC_USDT,ETH_USDT

# 美股 + 自动模拟盘
tradecat daemon --strategy us_fast_5m.yaml --auto-trade --notional 500
```

- `--symbols` 留空 → 使用策略内 `symbols`
- 信号写入：`libs/database/services/signal-service/signal_history.db`
- `source` 字段：`daemon_auto`

## paper 模拟盘

```bash
tradecat paper long NVDA --notional 1000 --price 120.5 --market us_stock
tradecat paper from-signal NVDA --side LONG --price 120.5 --market us_stock
tradecat paper status
```

环境变量：

| 变量 | 说明 |
|:---|:---|
| `PAPER_REPO_TYPE` | `sqlite`（默认）或 `memory` |
| `PAPER_DB_PATH` | 覆盖模拟盘库路径 |
| `PAPER_AUTO_MARKET` | TUI auto_consumer 默认 market（未设则从 `TUI_SIGNAL_STRATEGY` 读取） |

## backtest

```bash
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 3 --mode scan
```

| mode | 行为 |
|:---|:---|
| `scan` | 全历史 bar 扫描（默认） |
| `runner` | 仅最后两根 K 线（与线上一致） |
| `dry` | 只拉 K 线 |

`--paper` / `--no-paper`：是否输出简易模拟 PnL（`core/backtest/paper_sim.py`）。

## TUI

```bash
# 使用美股策略轮询
TUI_SIGNAL_STRATEGY=us_fast_5m.yaml \
TUI_SIGNAL_PROVIDER=us_equity \
PAPER_AUTO_MARKET=us_stock \
tradecat tui
```

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `TUI_SIGNAL_POLLER` | `1` | 后台策略扫描 |
| `TUI_SIGNAL_STRATEGY` | `current/fast_1m.yaml` | 策略路径 |
| `TUI_SIGNAL_PROVIDER` | （空=自动） | 覆盖 provider |
| `TUI_SIGNAL_POLL_INTERVAL_S` | `60` | 扫描间隔 |
| `TUI_SIGNAL_MIN_STRENGTH` | `50` | 写入 DB 阈值 |

## 只读桥接（Agent / 外部）

```bash
python3 scripts/tradecat_get_quotes.py --market us_stock NVDA META
python3 scripts/tradecat_get_signals.py --symbol NVDA --timeframe 5m --limit 5
```

行情模块路径：`src/tradecat/tui/quote.py`（已迁移，勿指向旧 `services-preview`）。
