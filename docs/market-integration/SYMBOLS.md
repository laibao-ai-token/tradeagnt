# 符号归一化

入口：`src/tradecat/core/symbols/__init__.py`

## 对外 API

| 函数 | 用途 |
|:---|:---|
| `normalize_market(str)` | 别名 → 标准 market |
| `normalize_symbol(symbol, market?)` | 转为 canonical |
| `normalize_symbols_for_strategy(symbols, market)` | 策略列表去重 |
| `default_provider_for_market(market)` | 默认数据源名 |
| `signal_symbol_for_engine(symbol, market)` | 送入引擎的 symbol（crypto 可能 compact） |

## 各市场 canonical 格式（约定）

| market | canonical 示例 | 禁止/注意 |
|:---|:---|:---|
| `crypto` | `BTC_USDT` | 不用裸 `BTCUSDT` 进 Paper |
| `us_stock` | `NVDA` | 去掉 `.US` 后缀 |
| `hk_stock` | `00700`（建议 5 位） | 与 TUI 一致 |
| `cn_stock` | `SH600519` / `SZ000001` | 带交易所前缀 |
| `cn_fund` | `510300` 或带前缀 | 见 TUI fund 模块 |

**新市场必须先在本表登记 canonical 规则**，再实现 `symbols/<market>.py`。

## 新增市场代码步骤

1. 创建 `src/tradecat/core/symbols/hk.py`（示例）：

```python
def normalize_hk_symbol(symbol: str) -> str:
    ...
```

2. 在 `__init__.py` 中：

```python
_MARKET_ALIASES["hk"] = "hk_stock"

def normalize_symbol(...):
    if m == "hk_stock":
        return normalize_hk_symbol(raw)
```

3. `default_provider_for_market`：

```python
if m == "hk_stock":
    return "hk_equity"
```

## 自动检测（兜底）

`market` 为空时：`normalize_symbol` 先尝试 crypto，再尝试 us_stock。  
**生产路径必须显式传 `market`**（策略 YAML 或 CLI `--market`），勿依赖自动检测。

## Paper / 信号库 一致性

- 写入 `signal_history.db` 的 `symbol` 列 = **canonical**
- `PaperTradingEngine` 仓位 `symbol` = **canonical**
- TUI 报价 symbol 与 canonical 对齐（见 `tui.py` `_match_signal_to_symbol`）
