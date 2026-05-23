# TradeCat v0.8 封板范围

> 封板日期：2026-05-23  
> 策略版本：`config/strategies/releases/20260523_v08_dual`（`current/`）  
> 验收命令：`./scripts/freeze_verify.sh`

## 包含（承诺可用）

| 能力 | 入口 |
|:---|:---|
| TUI 三页 + 加密/美股子页 | `TRADECAT_PIPELINE_PROFILE=tui_dual tradecat tui` |
| 双策略信号 + 模拟跟单 | pipeline / `TUI_SIGNAL_STRATEGY*` + `PAPER_AUTO_MARKET=all` |
| 按需行情 | Provider HTTP；`tradecat_get_quotes.py` |
| 只读信号 | `tradecat_get_signals.py` → `signal_history.db` |
| 策略发布 | `strategy_release.py bundle --activate` |
| 美股/加密 CLI | `tradecat signal|daemon|backtest|paper` + 策略 YAML |
| 采集口径 | **on-demand**（见 `docs/pipeline/DATA_COLLECTION.md`） |

## v1 抽离（封板后）

- 数据双轨与迁移：`data/`、`scripts/migrate_data_to_tradeagnt.sh`、`docs/MIGRATE_v0.8_to_v1.0.md`
- 独立版说明：`docs/STANDALONE.md`

## 不包含（已知缺口）

- 常驻 `collector-service` → TimescaleDB 7×24 落库
- 全量 `pytest tests/` 全绿（仅 freeze 子集门禁）
- 生产级美股 RTH 门控、多日 Walk-Forward 回测
- `PipelineContext` 统一 runner（profile 仅写 env）

## 打 tag（封板后）

```bash
./scripts/freeze_verify.sh
git tag -a v0.8.0 -m "TradeCat v0.8 demo freeze"
# git push origin v0.8.0   # 需要时自行 push
```

## Linear

封板相关 Issue：TRA-56～62、pipeline/data-collection、strategy `20260523_v08_dual`。
