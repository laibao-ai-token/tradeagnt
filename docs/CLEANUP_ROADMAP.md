# 清理与性能路线图（v0.8 → v1.0）

## 已完成（2026-05-23）

| 项 | 说明 |
|:---|:---|
| core 解耦 | `UsEquityProvider` 不再 import `tui.quote` |
| TUI 性能 | `fetch_recent_with_unfiltered` 单次查库 |
| 采集定案 | on-demand + `collector_on_demand.py` |
| 封板门禁 | `scripts/freeze_verify.sh` |

## P0（发版后 1～2 周）

- 拆分 `tui/tui.py`、`tui/quote.py`（按页/市场）
- `quote.py` 美股函数改为复用 `core/providers/us_market_http.py`
- 统一跟单：合并 `auto_consumer` 与 `SignalConsumer`
- 更新 `AGENTS.md` / `README` 去掉 `services/*` 叙述

## P1（v1.0 前）

- `core/pipeline` Runner 替代 env 拼装
- 全量测试与 freeze 子集对齐
- 文档归档 `ARCHITECTURE_ISSUES.md`（微服务时代）
