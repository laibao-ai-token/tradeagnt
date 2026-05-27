# tradeagnt

**独立终端交易助手** — 单体 Python 包 `src/tradecat`，面向加密 + 美股演示闭环（TUI、信号、模拟盘、按需行情）。

> 本仓库为 [laibao-ai-token/tradeagnt](https://github.com/laibao-ai-token/tradeagnt)。  
> 不是完整 TradeCat 微服务数据平台。历史上游文档见 [`docs/archive/README_legacy_tradecat_upstream.md`](docs/archive/README_legacy_tradecat_upstream.md)。

[English](README_EN.md) | 简体中文

[![License](https://img.shields.io/github/license/laibao-ai-token/tradeagnt)](LICENSE)

---

## 能力范围（v1.0 封板）

| 包含 | 不包含 |
|:---|:---|
| TUI 行情 / 信号 / 模拟盘（加密 + 美股） | 7×24 `collector-service` + TimescaleDB 全量管线 |
| 双策略包 `20260523_v08_dual` | 与上游 TradeCat 功能对齐 / 自动同步 |
| 按需行情、只读桥接脚本 | 生产级美股 RTH、全量 pytest 全绿 |

详见 [`docs/FREEZE_SCOPE.md`](docs/FREEZE_SCOPE.md)、[`docs/V1_AGENT_HARNESS.md`](docs/V1_AGENT_HARNESS.md)、[`skills/tradeagnt/agents/manifest.json`](skills/tradeagnt/agents/manifest.json)。

---

## 快速开始

### 1. 克隆与安装

```bash
git clone https://github.com/laibao-ai-token/tradeagnt.git
cd tradeagnt

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp config/.env.example config/.env
chmod 600 config/.env
# 按需编辑 config/.env（代理、数据库等）
```

### 2. 启动 TUI（推荐）

```bash
export TRADECAT_PIPELINE_PROFILE=tui_dual   # 或 TRADEAGNT_PIPELINE_PROFILE
tradecat tui
```

默认 **不** 拉起微服务采集（on-demand 行情）。需要时：

```bash
TUI_AUTO_START_COLLECTOR=1 tradecat tui
```

### 3. 封板验收

```bash
./scripts/freeze_verify.sh
```

---

## 常用命令

| 用途 | 命令 |
|:---|:---|
| 行情 JSON | `python scripts/tradecat_get_quotes.py NVDA` |
| 信号 JSON | `python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5` |
| 策略发布 | `python scripts/strategy_release.py show` |
| 回测 | `./scripts/backtest.sh --strategy current/fast_1m.yaml --symbol BTC_USDT --days 3` |
| 数据迁移（v1） | `./scripts/migrate_data_to_tradeagnt.sh` |
| 代码检查 | `./scripts/verify.sh` |

CLI：`tradecat signal`、`tradecat paper`、`tradecat daemon`、`tradecat backtest` 等（`tradecat --help`）。

---

## 目录结构（单体）

```text
tradeagnt/
├── src/tradecat/          # 应用代码（包名仍为 tradecat）
├── config/                # 策略、pipeline、.env.example
├── data/                  # v1 推荐本地 SQLite（见 data/README.md）
├── libs/database/         # v0.8 兼容旧数据路径
├── scripts/               # 启动、桥接、封板门禁
└── docs/                  # STANDALONE、FREEZE_SCOPE、迁移说明
```

---

## 配置要点

| 变量 | 说明 |
|:---|:---|
| `TRADECAT_PIPELINE_PROFILE` / `TRADEAGNT_PIPELINE_PROFILE` | 如 `tui_dual` |
| `TRADEAGNT_DATA_DIR` / `SIGNAL_DB_PATH` | 信号库路径（可选） |
| `PAPER_AUTO_MARKET` | 模拟盘市场（profile 可设为 `all`） |
| `TUI_AUTO_START_COLLECTOR` | 默认 `0` |

完整模板：`config/.env.example`。独立版精简：`config/.env.standalone.example`。迁移：`docs/MIGRATE_v0.8_to_v1.0.md`。

---

## 文档索引

| 文档 | 内容 |
|:---|:---|
| [docs/README.md](docs/README.md) | 文档总索引 |
| [docs/STANDALONE.md](docs/STANDALONE.md) | 独立版定位 |
| [docs/DETACH_CHECKLIST.md](docs/DETACH_CHECKLIST.md) | 脱离上游清单 |
| [docs/FREEZE_SCOPE.md](docs/FREEZE_SCOPE.md) | v1.0 封板承诺 |
| [docs/V1_AGENT_HARNESS.md](docs/V1_AGENT_HARNESS.md) | Agent Harness / 对齐官方路线图 |
| [docs/MIGRATE_v0.8_to_v1.0.md](docs/MIGRATE_v0.8_to_v1.0.md) | 路径与配置迁移 |
| [docs/pipeline/DATA_COLLECTION.md](docs/pipeline/DATA_COLLECTION.md) | on-demand 采集 |
| [AGENTS.md](AGENTS.md) | AI / 开发约束 |

---

## 贡献与许可

- Issue / PR：[github.com/laibao-ai-token/tradeagnt](https://github.com/laibao-ai-token/tradeagnt)
- 贡献指南：[.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)
- 许可：MIT（见 [LICENSE](LICENSE)）

若本仓库曾 Fork 自其他项目，可在 GitHub 仓库设置中使用 **Detach fork** 解除页面上的 Fork 关系（与代码无关）。
