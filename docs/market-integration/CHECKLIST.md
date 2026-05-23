# 新市场接入清单

复制本清单到新市场 Issue / PR 描述中，逐项勾选。

---

## Phase 0：设计确认

- [ ] 确定 `market` 枚举值（全小写+下划线，如 `hk_stock`）
- [ ] 确定 canonical symbol 格式（示例：`00700`、`SH600519`、`BTC_USDT`）
- [ ] 确定默认 Provider 名称（如 `hk_equity`）
- [ ] 确定 K 线来源（Tencent / Nasdaq / AKShare / PG / CSV）
- [ ] 填写 [examples/TEMPLATE_new_market.md](./examples/TEMPLATE_new_market.md)

---

## Phase 1：符号层 `core/symbols/`

- [ ] 新增 `src/tradecat/core/symbols/<market>.py`
  - `normalize_<market>_symbol(symbol) -> str`
  - `is_<market>_symbol(symbol) -> bool`（可选）
- [ ] 更新 `src/tradecat/core/symbols/__init__.py`
  - `_MARKET_ALIASES` 增加别名（如 `hk` → `hk_stock`）
  - `normalize_symbol()` 增加分支
  - `default_provider_for_market()` 增加映射
  - `signal_symbol_for_engine()` 如需特殊格式则扩展
- [ ] 单元测试：`tests/test_<market>_symbols.py`

---

## Phase 2：数据源 `core/providers/`

- [ ] 新增 `src/tradecat/core/providers/<market>_equity.py`（或通用 `equity.py`）
  - 实现 `DataProvider` 全部抽象方法
  - `fetch_klines` 返回列：`timestamp, open, high, low, close, volume`
  - `can_resolve` 与符号模块一致
  - 优先复用 `tui/quote.py` 已有函数，避免重复 HTTP
- [ ] `registry.py` → `auto_register()` 中 `register(...)`
- [ ] 单元测试：mock 行情，断言 DataFrame 非空、列齐全

---

## Phase 3：策略配置

- [ ] 新增 `config/strategies/<market>_fast_5m.yaml`
  - `market: <your_market>`
  - `symbols:` 列表
  - `timeframe:` 与 K 线能力一致
  - `rules:` 可先复制 RSI demo
- [ ] 更新 `config/strategies/README.md` 命令示例
- [ ] （可选）`python3 scripts/strategy_release.py snapshot --activate`

---

## Phase 4：运行时打通

- [ ] `tradecat signal --config <yaml> --symbol <sym>` 有信号或合理空结果
- [ ] `tradecat daemon --strategy <yaml>` 写 `signal_history.db`
- [ ] `tradecat paper long <sym> --market <market> --notional ... --price ...`
- [ ] `tradecat backtest --strategy <yaml> --symbol <sym> --days N`
- [ ] TUI：`TUI_SIGNAL_STRATEGY=<yaml> PAPER_AUTO_MARKET=<market> tradecat tui`
- [ ] （可选）`scripts/tradecat_get_quotes.py --market <market> <sym>` JSON 正常

---

## Phase 5：文档与回归

- [ ] 新增 `docs/market-integration/examples/<market>.md`
- [ ] `tests/` 相关用例通过
- [ ] 不破坏已有 `crypto` smoke（`BTC_USDT` daemon/signal）

---

## PR 自检问题

1. SignalEngine / PaperTradingEngine 是否 **没有** 新市场硬编码？
2. 新逻辑是否都可通过 `market` + Provider 关闭/切换？
3. 策略 YAML 是否可单独发布到 `releases/`？
