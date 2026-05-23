# 参考实现：美股（us_stock）

已落地，后续市场请对照本文件做 diff。

## 代码映射

| 能力 | 文件 |
|:---|:---|
| 符号 | `src/tradecat/core/symbols/equity.py` |
| Provider | `src/tradecat/core/providers/us_equity.py` |
| 注册 | `src/tradecat/core/providers/registry.py` |
| 映射 | `src/tradecat/core/symbols/__init__.py` |
| 策略 | `config/strategies/us_fast_5m.yaml` |
| 测试 | `tests/test_us_equity.py` |

## 数据流

1. 策略 `market: us_stock` → `default_provider_for_market` → `us_equity`
2. `UsEquityProvider.fetch_klines`：Nasdaq 1m → 不足则 Tencent → resample 到 5m
3. `SignalEngine.run` / `scan_history` 与 crypto 相同
4. Paper `from_signal` 带 `market: us_stock`，symbol 存 `NVDA`

## 命令速查

```bash
tradecat signal --config us_fast_5m.yaml --symbol NVDA
tradecat daemon --strategy us_fast_5m.yaml --auto-trade --notional 500
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 3
tradecat paper long NVDA --notional 1000 --price 120 --market us_stock
```

## 交易语义（与 crypto 差异）

- **BUY**：开多（LONG）
- **SELL**：**平多**（CLOSE），不开空仓（与 `paper_sim` 回测一致）
- TUI `auto_consumer` 从 `TUI_SIGNAL_STRATEGY` 推断 `market`；可显式设 `PAPER_AUTO_MARKET=us_stock`

## 已知限制

- K 线： primarily **当日 intraday**（约 ≤390 根 1m），多日历史需后续 Provider 增强
- 非交易时段：可能无新 bar，信号为空属正常

## 港股 / A 股可复用点

- `tui/quote.py` 已有 `hk_stock` / `cn_stock` 的 Tencent 报价与分钟线
- 接入时复制 `us_equity.py` 结构，改 `market` 常量与 quote 调用即可
