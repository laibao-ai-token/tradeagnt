# v0.8 → tradeagnt v1.0 迁移

## 数据路径

| v0.8 | v1（推荐） |
|:---|:---|
| `libs/database/services/signal-service/signal_history.db` | `data/signal_history.db` |
| 同目录 `.paper_trading.db` | `data/.paper_trading.db` |

```bash
./scripts/migrate_data_to_tradeagnt.sh
```

未迁移时 v1 仍会**只读**旧路径；写入请迁到 `data/`。

## 环境变量

| 旧 | 新（可选） |
|:---|:---|
| `TRADECAT_PIPELINE_PROFILE` | `TRADEAGNT_PIPELINE_PROFILE`（二者均支持） |
| — | `TRADEAGNT_DATA_DIR` / `SIGNAL_DB_PATH` |

## 策略

封板包：`config/strategies/releases/20260523_v08_dual`（`current/` 应指向该目录）。

## 不再支持（除非显式开启）

- `services/signal-service` 129 规则桥：`TRADEAGNT_LEGACY_RULES=1`
- 微服务 `collector-service` 7×24 采集（独立版为 on-demand）

## 验收

```bash
./scripts/freeze_verify.sh
```
