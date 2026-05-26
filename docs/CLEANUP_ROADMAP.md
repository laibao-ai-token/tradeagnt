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
- ~~更新 `README` / FUNDING / CONTRIBUTING 去掉上游痕迹~~（2026-05：已完成，旧 README 在 `docs/archive/`）
- ~~更新 `AGENTS.md` / `start.sh` / `init.sh` 单体化~~（2026-05：已完成）

## P1（v1.0 前）

- `core/pipeline` Runner 替代 env 拼装
- 全量测试与 freeze 子集对齐

## 已完成（独立化第五步）

- 微服务文档迁至 `docs/archive/microservices-era/`
- `docs/README.md`、`docs/DETACH_CHECKLIST.md`
- 原 `ARCHITECTURE_ISSUES.md` 等保留跳转 stub

## 已完成（独立化第四步）

- `config/.env.standalone.example`
- `.github/workflows/ci.yml` → `src/tradecat` + `freeze_verify`
- `scripts/backtest.sh` → `tradecat backtest`
- `check_no_print_services.py` → 扫描 `src/tradecat`
