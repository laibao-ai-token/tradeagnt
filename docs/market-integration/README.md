# 交易市场接入文档

本目录定义 TradeCat **接入新交易标的（市场）** 的固定原则与操作步骤。

适用：`crypto`（已有）、`us_stock`（已接入）、以及后续的 `hk_stock`、`cn_stock`、`cn_fund` 等。

> **目标**：新市场只「登记 + 实现 Provider/符号」，不重写 SignalEngine、PaperTrading、CLI 主流程。

---

## 文档索引

| 文档 | 内容 |
|:---|:---|
| [PRINCIPLES.md](./PRINCIPLES.md) | 架构原则、边界、禁止事项 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 分层与数据流（Mermaid） |
| [CHECKLIST.md](./CHECKLIST.md) | **接入清单**（按顺序勾选） |
| [STRATEGY_YAML.md](./STRATEGY_YAML.md) | 策略 YAML 约定与 `market` 字段 |
| [PROVIDER.md](./PROVIDER.md) | `DataProvider` 实现规范 |
| [SYMBOLS.md](./SYMBOLS.md) | 符号归一化与市场映射 |
| [CLI_AND_RUNTIME.md](./CLI_AND_RUNTIME.md) | CLI / daemon / TUI / 环境变量 |
| [TESTING.md](./TESTING.md) | 测试与验收命令 |
| [examples/us_stock.md](./examples/us_stock.md) | 美股参考实现（已落地） |
| [examples/TEMPLATE_new_market.md](./examples/TEMPLATE_new_market.md) | 新市场接入填空模板 |

---

## 快速判断：你要接的是什么？

```text
新市场 = 一个新的 market 枚举值 + 一套符号规则 + 一个（或多个）DataProvider
```

策略、信号、模拟盘、回测 **共用同一套引擎**；差异只在：

1. `config/strategies/*.yaml` 里的 `market` / `symbols`
2. `src/tradecat/core/symbols/` 里的归一化
3. `src/tradecat/core/providers/` 里的 K 线/报价
4. `symbols/__init__.py` 里的 `default_provider_for_market()` 映射

---

## 推荐接入顺序

1. 读 [PRINCIPLES.md](./PRINCIPLES.md) + [ARCHITECTURE.md](./ARCHITECTURE.md)
2. 复制 [examples/TEMPLATE_new_market.md](./examples/TEMPLATE_new_market.md) 填表
3. 按 [CHECKLIST.md](./CHECKLIST.md) 逐项实现
4. 对照 [examples/us_stock.md](./examples/us_stock.md) 做 diff
5. 跑 [TESTING.md](./TESTING.md) 里的 smoke 命令

---

## 目录与代码映射

```text
docs/market-integration/          ← 本文档（原则，不随业务频繁改）
config/strategies/                ← 各市场策略 YAML + releases/
src/tradecat/core/
  symbols/                        ← 市场符号归一化（按市场分文件）
  providers/                      ← DataProvider 插件
  signals/                        ← SignalEngine（勿为单市场改逻辑）
  paper_trading/                  ← 模拟盘（通过 market 区分标的）
  backtest/                       ← 简易回测 PnL（市场无关）
src/tradecat/cli/                 ← signal / daemon / backtest / paper
src/tradecat/tui/quote.py         ← 行情抓取（可复用到 Provider）
```

---

## 变更记录

| 日期 | 说明 |
|:---|:---|
| 2026-05-22 | 初版：固化 crypto + us_stock 接入原则，预留 hk/cn 扩展位 |
