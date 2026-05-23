# 数据采集口径（v0.8 封板）

## 结论

**单体仓 `src/tradecat/` 封板采用「按需行情」（on-demand）**，不依赖 `services/collector-service` 常驻落库。

| 能力 | 封板内 | 封板外（后续） |
|:---|:---|:---|
| TUI / CLI 实时报价 | ✅ Provider HTTP（Gate、Tencent、Yahoo 等） | — |
| 信号 / 模拟盘 / 回测 | ✅ 读实时 K 线 + `signal_history.db` | — |
| TimescaleDB 7×24 K 线采集 | ❌ | 恢复或外接 collector |
| 指标表 SQLite 全量回填 | ❌ | trading-service 链 |

## 怎么用

```bash
# TUI（默认不拉起 collector）
tradecat tui

# 显式查看采集剖面（无 collector 目录时返回 on-demand JSON）
./scripts/start.sh status-collector

# 新闻可选轻量同步（PG）
./scripts/start_news_sync.sh
```

## 环境变量

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `TUI_AUTO_START_COLLECTOR` | `0` | `1` 时才尝试 `start-collector` |
| `TRADECAT_DATA_MODE` | `on_demand` | 由 `scripts/lib/collector_on_demand.py` 写入 status JSON |

## 验收

```bash
./scripts/start.sh status-collector | python3 -m json.tool
pytest tests/test_start_script.py tests/test_script_alignment.py -q
```
