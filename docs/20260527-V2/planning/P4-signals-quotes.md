# P4 — 信号与行情

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已锁定（2026-05-28） |
| 总表 | [PLANNING.md](../PLANNING.md) § P4 |
| 依赖 | P1 ✅ · P2 ✅ · P3 ✅ |

## 要拍板什么

- 行情、信号（及 Agent 工具）数据从哪来？
- V2.0 是否引入公开表 / Agent 自备数据源？

## 决策（已锁定）

- **原则**：**基于现有 tradeagnt 基建**；有需求再扩展，V2.0 **不先加新源**。

| 数据类 | V2.0 来源 | 工具/路径 |
|:---|:---|:---|
| **行情** | 现有 Provider（crypto + us_stock 等） | `tradecat_get_quotes.py`、`context_pack` |
| **信号** | 本地策略 → `signal_history.db`（`data/` 优先） | `tradecat_get_signals.py` |
| **资讯** | 现有 PG/SQLite 新闻链 + RSS 配置 | `tradecat_get_news.py` |
| **回测摘要** | 已有 artifacts / run_id | `tradecat_get_backtest_summary.py` |
| **TUI→Pi 快照** | 右 TUI 当前态（P3 字段） | 实现阶段暴露，不新接外部源 |

### 明确不做（V2.0）

- 公开 Google 表 `signal_flow` 等（**有需求再 P4.x / V2.1**）
- Agent 自备第三方行情/API（**有需求再扩展**）
- 7×24 TimescaleDB 全量管线
- 为 V2 新建独立采集服务

### 与 Pi 的关系

- Pi Skills/Extensions **只包装上述现有脚本/CLI**，不先造新数据管道。

## 主 Agent 记录

- 2026-05-28：用户确认 — 沿用现有基建，后续有需求再补充。
