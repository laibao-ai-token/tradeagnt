# tradeagnt v1.0 封板范围

> 封板日期：2026-05-27  
> 主分支：`tradeagnt`  
> 策略包：`config/strategies/releases/20260523_v08_dual`（`current/`）  
> 验收：`./scripts/freeze_verify.sh`

## 产品定位（v1.0）

**tradeagnt** 独立单体：给人用的 TUI 演示闭环 + **给 Agent 用的只读 JSON 工具层**（下一步在 [V1_AGENT_HARNESS.md](./V1_AGENT_HARNESS.md) 扩展写入与 manifest）。

不再使用 v0.8 作为对外版本号；`v0.8.0` tag 保留为历史里程碑。

## 包含（承诺可用）

| 能力 | 入口 |
|:---|:---|
| TUI 三页 + 加密/美股子页 | `TRADECAT_PIPELINE_PROFILE=tui_dual tradecat tui` |
| 双策略 + 模拟跟单 | pipeline / `PAPER_AUTO_MARKET=all` |
| 按需行情 | Provider；`tradecat_get_quotes.py` |
| 只读信号/新闻/回测摘要 | `tradecat_get_signals.py` 等 |
| 研究上下文打包 | `tradecat_get_context_pack.py` |
| Agent 工具清单（机器可读） | `skills/tradeagnt/agents/manifest.json` |
| 策略发布 | `strategy_release.py bundle --activate` |
| CLI | `tradecat signal|paper|daemon|backtest` |
| 采集 | on-demand（`docs/pipeline/DATA_COLLECTION.md`） |

## 不包含（v1.0 不承诺）

- 官方 TradeCat Public 全链路（表格信号、`agent_trade_thesis` 闸门、Hermes 同款 paper loop）
- 7×24 `collector-service` + TimescaleDB 全量管线
- 全量 `pytest` 全绿（仅 freeze 子集）
- 生产级美股 RTH、完整 Walk-Forward 回测平台
- `PipelineContext` 统一 runner（profile 仍写 env）

## 打 tag

```bash
./scripts/freeze_verify.sh
git tag -a v1.0.0 -m "tradeagnt v1.0 — standalone + agent read APIs"
git push origin tradeagnt v1.0.0
```

## 与官方对齐（v1.1+）

见 [V1_AGENT_HARNESS.md](./V1_AGENT_HARNESS.md)。
