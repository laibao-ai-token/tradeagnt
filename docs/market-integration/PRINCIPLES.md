# 接入原则

## 1. 单一真相：`market` 驱动一切

- 策略 YAML 必须声明 `market`（如 `crypto`、`us_stock`、`hk_stock`、`cn_stock`）。
- CLI / daemon / TUI poller **从策略读取 `market`**，再选择 Provider 与符号归一化方式。
- **禁止**在 SignalEngine、PaperTradingEngine 内写 `if symbol == "NVDA"` 这类市场特例。

## 2. 插件化数据源

- 所有行情/K 线通过 `DataProvider`（`core/providers/base.py`）接入。
- 新市场 = 新 Provider（或带 `market` 参数的通用 Equity Provider）+ `ProviderRegistry.register()`。
- Provider 只负责：标准 OHLCV DataFrame、`fetch_latest`、 `can_resolve(symbol)`。

## 3. 符号与行情分离

| 模块 | 职责 |
|:---|:---|
| `core/symbols/*` | 输入清洗、canonical 形式（如 `BTC_USDT`、`NVDA`、`00700`） |
| `core/providers/*` | 拉 K 线/报价 |
| `tui/quote.py` | 终端展示用行情（Provider 可复用其实现） |

## 4. 引擎层零分叉

以下模块 **不因新市场而复制**：

- `SignalEngine`（`core/signals/engine.py`）
- `StrategyLoader` / `RuleConfig`（`core/signals/strategy.py`）
- `PaperTradingEngine` 主流程（仅通过 `market` 归一化 symbol）
- `tradecat backtest` 的 `scan_history` 扫描逻辑

## 5. 模拟盘统一账户模型

- 一个 Paper 账户可持有多市场标的，靠 **symbol 字符串 + market 元数据** 区分。
- 下单路径统一：`paper long <symbol> --market <market>` 或 `from_signal` 带 `market` 字段。
- 计价货币在展示层区分（crypto 常用 USDT，股票常用 USD/CNY），不在引擎里写死。

## 6. 配置与版本化

- 策略文件放在 `config/strategies/`，生产使用 `current/` 指针 + `releases/<id>/` 快照。
- 新市场先加 `config/strategies/<market>_fast_5m.yaml`，通过 `scripts/strategy_release.py` 打 release。

## 7. 禁止事项

- **不要**为新市场单独写一套 `daemon_us.py` / `backtest_hk.py`。
- **不要**在 TUI 里实现策略逻辑（TUI 只展示 + 轮询写 `signal_history.db`）。
- **不要**跳过 `market` 字段，靠 symbol 形态猜测市场（自动检测仅作兜底）。
- **不要**修改 `config/.env` 生产文件；新配置项写入 `config/.env.example` 并文档化。

## 8. 演进方向（推荐）

将 `symbols/__init__.py` 中的 `if market == "us_stock"` 逐步收敛为 **Market Registry 表驱动**：

```python
# 目标形态（示意）
MARKET_REGISTRY = {
    "us_stock": MarketSpec(normalize=..., default_provider="us_equity", ...),
    "hk_stock": MarketSpec(...),
}
```

新市场 = 注册表增加一行 + 实现 Provider，而不是散落 if/else。
