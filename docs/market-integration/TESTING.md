# 测试与验收

## 单元测试

```bash
cd /path/to/tradeagnt
PYTHONPATH=src .venv/bin/python -m pytest tests/test_us_equity.py -v
```

新市场建议新增：

- `tests/test_<market>_symbols.py` — 归一化边界
- `tests/test_<market>_provider.py` — mock 行情 → DataFrame

## Smoke（需网络）

```bash
export PYTHONPATH=src

# 1. 信号
tradecat signal --config us_fast_5m.yaml --symbol NVDA

# 2. 回测扫描
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 2 --mode scan

# 3. 模拟盘
tradecat paper long NVDA --notional 500 --price 100 --market us_stock
tradecat paper status

# 4. 报价 JSON
python3 scripts/tradecat_get_quotes.py --market us_stock NVDA
```

## 回归 crypto

```bash
tradecat signal --config fast_1m.yaml --symbol BTC_USDT --provider gate
```

## 验收标准

| 项 | 通过条件 |
|:---|:---|
| 符号 | `normalize_symbol` 对典型输入稳定 |
| K 线 | `fetch_klines` ≥50 行，含 OHLCV 列 |
| 信号 | `signal` 或 `backtest --mode scan` 不崩溃；有/无信号均可 |
| 模拟盘 | `paper long` 返回 ok，DB 有仓位 |
| 隔离 | crypto 命令结果与接入前一致 |

## CI 建议

- 单元测试 mock 网络，不依赖外网
- Smoke 放 manual / nightly workflow
