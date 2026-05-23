# TradeCat - AI Agent 操作手册

> 本文档面向 AI 编码 Agent，以可执行指令的视角编写，约束与指导 Agent 行为。

---

## 0. 仓库现状（2026-05，模块化单体）

本仓库 **`tradeagnt` / tradecat v0.8** 已从多微服务目录收敛为 **单一 Python 包**：

| 现状 | 说明 |
|:---|:---|
| **主代码** | `src/tradecat/`（`cli` / `core` / `tui` / `common`） |
| **入口** | `tradecat` CLI（`pyproject.toml` → `tradecat.cli.main`） |
| **无 `services/`** | 旧路径 `services/*`、`services-preview/*` **已不在本仓**；勿再引用 |
| **策略** | `config/strategies/`（含 `current/`、`us_fast_5m.yaml`） |
| **任务跟踪** | **Linear（MCP）** 为 SSOT；本地 `.issues/` 仅草稿 |

新市场接入：`docs/market-integration/README.md`。  
Pipeline 固化（单一运行上下文）：`docs/pipeline/README.md`，剖面配置 `config/pipeline/*.yaml`。

---

## 1. Mission & Scope（目标与边界）

### 1.1 允许的操作

- 修改 `src/tradecat/` 下业务代码（`cli/`、`core/`、`tui/`、`common/`）
- 修改 `config/.env.example`、策略 YAML（`config/strategies/`）
- 添加/修改指标（`src/tradecat/core/indicators/`）
- 添加/修改 Provider（`src/tradecat/core/providers/`）
- 添加/修改 TUI（`src/tradecat/tui/`）
- 修改启动与工具脚本（`scripts/`）
- 更新文档（`README.md`、`README_EN.md`、`AGENTS.md`、`docs/`）
- 修改根目录 `Makefile`、`pyproject.toml`、`.cursor/` MCP 与规则

### 1.2 禁止的操作

- **禁止修改** `config/.env` 生产配置文件
- **禁止修改** 数据库 schema（除非明确要求）
- **禁止删除** `libs/database/` 下的数据文件
- **禁止修改** `.gitignore` 中已忽略的敏感文件
- **禁止** 大范围重构，除非任务明确要求
- **禁止** 添加未经验证的第三方依赖

### 1.3 敏感区域

| 路径 | 说明 | 操作限制 |
|:---|:---|:---|
| `config/.env` | 生产配置（含密钥） | 只读 |
| `libs/database/services/telegram-service/market_data.db` | SQLite 指标数据 | 只读 |
| `libs/database/services/signal-service/cooldown.db` | 信号冷却持久化 | 只读 |
| `libs/database/services/signal-service/signal_history.db` | 信号触发历史 | 只读 |
| `backups/timescaledb/` | 数据库备份 | 禁止修改 |

> 提醒：服务启动脚本会检查 `config/.env` 权限（需 600/400），不符合直接退出。

### 1.4 Multi-Agent 协作原则

- **默认强制优先使用 multi-agent**：只要任务可以安全拆分，就应优先并行使用多个 Agent 处理检索、分析、实现、验证等子任务，以缩短端到端完成时间
- **单 Agent 需要例外理由**：只有在任务强依赖同一上下文、改动极小、写入区域高度重叠，或串行处理明显更安全时，才允许退回单 Agent；执行前应先评估是否存在可并行切分点
- **推荐拆分方式固定化**：优先按“代码检索 / 文档核对 / 实现改动 / 测试验证”或“不同目录 / 不同服务 / 不同文件所有权”切分，让多个 Agent 并行推进
- **必须声明边界与归属**：多 Agent 并行时需明确职责边界、文件归属和最终产出，避免重复分析、重复实现，或同时修改同一文件造成相互覆盖
- **主 Agent 负责收敛与决策**：主 Agent 负责汇总结论、整合改动、冲突裁决与最终交付，不得将关键决策完全下放给子 Agent

### 1.5 终端命令与上下文保护（Token 节约）

执行任何可能产生大量文本输出的系统命令前（如全量 `pytest -v`、`git diff` 无范围、大规模 `find`/`rg`、回测/采集日志），先评估输出量：

- 预期超过约 **20 行** 时：用 `head`/`tail`、`grep`/`rg` 过滤，或只汇报统计摘要
- 输出体量未知时，默认：`COMMAND 2>&1 | head -c 4000`
- 测试/构建失败：优先保留失败用例与关键栈；完整日志写入文件，对话中只给路径
- **禁止**将完整冗长日志直接灌入上下文；需要细节时再针对性读取

与 [RTK](https://github.com/rtk-ai/rtk) 配合：Shell 命令经 hook 自动压缩；内置 Read/Grep 读大文件时仍应主动限范围。

### 1.6 Linear 任务跟踪（MCP + 规则驱动，必遵）

- **SSOT**：需求、Bug、迭代只在 **Linear（团队 TRA）**；规范见 [`docs/linear-issue-spec.md`](docs/linear-issue-spec.md)。
- **活跃项目**：仅 **`TradeCat v0.8`** 可新建 Issue；`tradeagent` / `Archive: 008 monolith` 已归档。
- **标签**：必带 `area:tui|paper|us-stock|core|docs|infra` 之一 + `Feature|Bug|Improvement`。
- **配置**：`.cursor/mcp.json` + `config/.env` 的 `LINEAR_API_KEY`；见 [`docs/linear-mcp-setup.md`](docs/linear-mcp-setup.md)。
- **Agent 规则**：`.cursor/rules/linear-workflow.mdc`（`alwaysApply`）。
- **本地 `.issues/`**：仅草稿；合并后标注 `superseded-by: TRA-xx`（见 [`.issues/README.md`](.issues/README.md)）。

---

## 2. Golden Path（推荐执行路径）

### 2.1 最短可复现场景

```bash
cd /path/to/tradeagnt

# 1) 虚拟环境与依赖（根目录单一 .venv）
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2) 配置
cp config/.env.example config/.env && chmod 600 config/.env

# 3) 验证
./scripts/verify.sh
tradecat --help
```

> 可选：`./scripts/init.sh` / `./scripts/install.sh` 与历史部署脚本兼容；**新开发以 `tradecat` CLI + `src/tradecat` 为准**。

### 2.2 TUI 与守护进程（当前主路径）

```bash
source .venv/bin/activate

# TUI（三页：P1 行情 / P2 模拟盘 / P3 资讯；子页 1=加密 2=美股，仅 t 切大页）
./scripts/start.sh run
# 或
tradecat tui

# 加密 + 美股双策略 + 双市场模拟盘跟单
TUI_SIGNAL_STRATEGY=current/fast_1m.yaml \
TUI_SIGNAL_STRATEGY_EXTRA=us_fast_5m.yaml \
PAPER_AUTO_MARKET=all \
tradecat tui

# 信号 / 守护 / 模拟盘 / 回测（模块化 CLI）
tradecat signal --config config/strategies/us_fast_5m.yaml --symbol NVDA
tradecat daemon --strategy us_fast_5m.yaml --auto-trade
tradecat paper status
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 3
```

> `./scripts/start.sh` 仍可用于 `run`、collector 占位、daemon；底层逐步收敛到 `tradecat` 子命令。

### 2.3 只读桥接命令

```bash
python scripts/tradecat_get_quotes.py NVDA
python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5
python scripts/tradecat_get_news.py --symbol BTCUSDT --limit 5 --since-minutes 120
python3 scripts/tradecat_get_backtest_summary.py --run-id <run_id>
```

约定：
- 这些命令是稳定的本地只读桥接入口
- 供上层编排或外部运行时消费
- TradeCat 主仓内不再维护旧 workbench / skill 路线

### 2.4 开发/修改流程

```bash
source .venv/bin/activate

# 1. Linear：确认/创建 Issue（MCP 或网页）
# 2. 修改 src/tradecat/ ...
ruff check src/tradecat tests
pytest tests/ -q --tb=no 2>&1 | tail -20

# 3. 验证
./scripts/verify.sh

# 4. 文档：README / AGENTS / docs/market-integration / config/.env.example
# 5. Linear：Issue 标 Done + 验证命令
```

---

## 3. Must-Run Commands（必须执行的命令清单）

### 3.0 tradecat CLI（主入口）

| 命令 | 说明 |
|:---|:---|
| `tradecat tui` | 终端看板（行情 / 模拟盘 / 资讯） |
| `tradecat signal` | 单标的策略信号 |
| `tradecat daemon` | 周期扫描 + 可选自动模拟盘 |
| `tradecat paper` | 模拟盘账户与下单 |
| `tradecat backtest` | 策略回测（YAML，`--market` 支持 `us_stock`） |
| `tradecat fetch` / `indicator` / `analyze` | 数据拉取与指标分析 |
| `tradecat migrate` | 数据库迁移 |

安装：`pip install -e .` 后可直接调用；开发时 `PYTHONPATH=src` 亦可。

### 3.1 全局脚本

| 命令 | 说明 |
|:---|:---|
| `./scripts/init.sh` | 初始化环境（历史脚本；新仓优先 `pip install -e ".[dev]"`） |
| `./scripts/init.sh <service>` | 初始化单个服务 |
| `./scripts/init.sh --all` | 初始化全部服务（含 preview + collector-service） |
| `./scripts/start.sh start\|stop\|status\|restart` | 核心服务管理 |
| `./scripts/start.sh daemon\|daemon-stop` | 守护进程模式（自动重启崩溃服务） |
| `./scripts/start.sh start-collector [--only=...][--exclude=...]` | 显式运行 collector-service 占位入口（透传选择器） |
| `./scripts/start.sh status-collector [--only=...][--exclude=...]` | 查看当前 collector-service 启用模块（透传选择器） |
| `./scripts/check_env.sh` | 环境检查（Python/依赖/配置/网络/数据库） |
| `./scripts/verify.sh` | 代码验证（ruff + py_compile + i18n） |
| `python scripts/tradecat_get_quotes.py NVDA` | 只读行情 JSON 命令（支持单/多 symbol，必要时显式传 `--market`） |
| `python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5` | 只读最近信号 JSON 命令（默认读 `signal_history.db`） |
| `python scripts/tradecat_get_news.py --symbol BTCUSDT --limit 5 --since-minutes 120` | 只读最近新闻 JSON 命令（读取 `<ALTERNATIVE_DB_SCHEMA>.news_articles`，默认 `alternative.news_articles`） |
| `python3 scripts/tradecat_get_backtest_summary.py --run-id <run_id>` | 只读已有回测摘要 JSON 命令（不触发重新回测） |
| `python scripts/data/download_hf_data.py` | 从 HuggingFace 下载历史数据并导入 |
| `python scripts/quality/check_i18n_keys.py` | 检查 i18n 翻译键对齐 |
| `python scripts/data/sync_market_data_to_rds.py` | 增量同步 SQLite `market_data.db` 到 PostgreSQL（RDS/Aurora） |
| `tradecat backtest --strategy config/strategies/fast_1m.yaml --symbol BTC_USDT` | **当前推荐** 模块化回测 |
| `./scripts/backtest.sh` | **遗留** 回测脚本转发（依赖旧 signal-service 布局时可能需适配） |
| `cd services/signal-service && python -m src.backtest ...` | **已废弃路径**（本仓无 `services/`） |
| `./scripts/backtest.sh --run-id tune-b-strict --long-threshold 90 --short-threshold 90 --close-threshold 15` | 回测参数调优示例（阈值覆盖） |
| `./scripts/backtest.sh --mode offline_replay --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | 覆盖不足时使用离线信号回放（基于 K 线生成信号） |
| `./scripts/backtest.sh --mode offline_rule_replay --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | 使用 SQLite 129 规则离线重放（不依赖 signal_history；当 timeframe=1m 时默认规则周期自动按 1m 对齐） |
| `./scripts/backtest.sh --mode compare_history_rule --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | 输出历史信号 vs 129规则离线重放对比报告（comparison.json/.md，含 missing 规则未命中原因诊断；会输出 `rule_timeframe_profiles` 并标记 `timeframe_no_data`，默认不受 signal days/count 门槛限制） |
| `./scripts/backtest.sh --mode compare_history_rule --alignment-min-score 70 --alignment-max-risk-level medium --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | 对齐 gate 示例：若 `alignment_score` 低于阈值或 `alignment_risk_level` 高于阈值则返回退出码 2，适合本地检查 / CI |
| `./scripts/backtest.sh --check-only --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | 回测前覆盖率检查（仅检查不执行） |
| `./scripts/backtest.sh --check-only --min-signal-days 7 --min-signal-count 200 --min-candle-coverage-pct 95` | 覆盖率门槛防呆（不足时失败，可加 `--force` 继续） |
| `./scripts/backtest.sh --symbols BTCUSDT,ETHUSDT --initial-equity 3000 --leverage 2 --position-size-pct 0.2` | 回测资金口径覆盖示例（本金/杠杆/仓位） |
| `./scripts/backtest.sh --config src/backtest/strategies/default.crypto.btc_eth.safe.yaml` | BTC/ETH 保守模板（阈值 200/200，低频） |
| `./scripts/backtest.sh --walk-forward --wf-train-days 7 --wf-test-days 3 --wf-step-days 3 --walk-forward-max-folds 6 --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"` | Walk-Forward（滚动窗口）回测摘要输出；默认会在训练窗对 `base/aggressive/conservative` 候选做轻量选参，`walk_forward_summary.json/metrics.json` 会记录每折 `selected_params` |
| `./scripts/backtest/real_window_validation.sh --dry-run` | 真实窗口校准闭环脚本（`check-only / compare gate / history_signal / walk-forward`）；`--dry-run` 可在 TimescaleDB 未恢复时先预览命令 |
| `python3 scripts/backtest/backtest_issue_fill.py --run-prefix <run_prefix> --print` | 从真实窗口校准产物中提取 `#006-01/#006-02/#006-03/#006-04` 的 issue 回填草稿；加 `--apply-issues` 可直接写回 issue 文件 |
| `./scripts/backtest.sh --walk-forward --walk-forward-auto-fallback --min-signal-days 7 --min-signal-count 200` | Walk-Forward 分折自动回放兜底（历史信号不足时切 offline_replay） |
| `./scripts/data/export_timescaledb.sh` | 导出 TimescaleDB 数据（默认端口 5434） |
| `./scripts/data/export_timescaledb_main4.sh` | 导出 Main4 精简数据集（默认端口 5434） |
| `./scripts/data/timescaledb_compression.sh` | 压缩管理（默认端口 5434） |

### 3.2 Make 快捷命令

| 命令 | 说明 |
|:---|:---|
| `make init` | 初始化所有服务 |
| `make install` | 一键安装（等价 `./scripts/install.sh`） |
| `make start` | 启动所有服务 |
| `make stop` | 停止所有服务 |
| `make status` | 查看服务状态 |
| `make daemon` | 启动守护进程（自动重启） |
| `make daemon-stop` | 停止守护进程 |
| `make verify` | 代码验证 |
| `make clean` | 清理缓存 |
| `make backtest` | 运行 signal-service 回测（M1） |
| `make export-db` | 导出 TimescaleDB 数据 |

### 3.3 根目录 Makefile

```bash
make install   # ./scripts/install.sh
make verify    # ruff + compileall（src/tradecat）
make test      # 建议在 venv 内：pytest tests/
make start     # ./scripts/start.sh start（遗留多进程占位）
make backtest  # ./scripts/backtest.sh（遗留）
```

> 旧文档中的「每服务独立 Makefile / .venv」**不再适用**；统一使用根目录 `.venv` + `pyproject.toml`。

### 3.4 数据库操作

> **端口说明**：`config/.env.example` 与导出/压缩脚本默认端口均为 **5434**（新库）；**5433** 旧库仅保留给历史迁移场景。请根据实际部署选择统一端口。

```bash
# 连接 TimescaleDB（根据 config/.env 中 DATABASE_URL 端口）
# 新库（5434）
PGPASSWORD=postgres psql -h localhost -p 5434 -U postgres -d market_data

# 旧库（5433，历史迁移）
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data

# 查看 K线数据量
SELECT COUNT(*) FROM market_data.candles_1m;

# 连接 SQLite
sqlite3 libs/database/services/telegram-service/market_data.db
```

---

## 4. Code Change Rules（修改约束）

### 4.1 架构原则

- **模块化单体**：单一包 `tradecat`，按层划分 `cli` / `core` / `tui`
- **市场插件化**：`StrategyConfig.market` → `symbols` + `Provider` → 共用 `SignalEngine` / `PaperTrading`
- **配置统一**：`config/.env` + `config/strategies/*.yaml`
- **数据**：TimescaleDB（K 线）+ SQLite（`libs/database/services/signal-service/` 信号/冷却/模拟盘）

### 4.2 模块清单（`src/tradecat/`）

| 模块 | 路径 | 职责 |
|:---|:---|:---|
| CLI | `cli/` | `tradecat` 子命令：signal、daemon、paper、backtest、tui |
| 信号 | `core/signals/` | 策略加载、规则引擎、冷却 |
| 指标 | `core/indicators/` | 指标注册与计算 |
| 数据 | `core/providers/` | 行情/K 线（crypto `gate`、美股 `us_equity` 等） |
| 符号 | `core/symbols/` | 按市场归一化标的 |
| 模拟盘 | `core/paper_trading/` | 账户、持仓、成交、账本 |
| 回测 | `core/backtest/` | 回测仿真 |
| TUI | `tui/` | 终端 UI、报价轮询、自动跟单 |

### 4.3 模块边界

| 层 | 允许 | 禁止 |
|:---|:---|:---|
| `core/providers` | 拉行情/K 线 | 写信号库、改 UI |
| `core/signals` | 检测信号、写 `signal_history.db` | 依赖 curses/TUI |
| `core/paper_trading` | 模拟成交、账本 | 直连交易所实盘 |
| `tui` | 展示、轮询、消费信号进模拟盘 | 内嵌业务规则（应调 `core`） |

> 冷却与信号历史路径：`libs/database/services/signal-service/cooldown.db`、`signal_history.db`（只读除非任务明确要求）。

### 4.4 依赖添加规则

1. 添加依赖前检查根目录 `pyproject.toml` 是否已有
2. 写入 `[project.dependencies]` 或 `[project.optional-dependencies.dev]`
3. `pip install -e ".[dev]"` 验证
4. 禁止未经验证的第三方依赖

### 4.5 兼容性要求

- Python **>= 3.12**（`pyproject.toml` / `.python-version`）
- 保持现有 DB schema 兼容（无明确要求不改 schema）
- 新指标注册到 `src/tradecat/core/indicators/__init__.py`
- 新 Provider 注册到 `src/tradecat/core/providers/registry.py`

---

## 5. Style & Quality（风格与质量标准）

### 5.1 代码风格

- **格式化**：遵循 PEP 8，使用 ruff
- **行长**：120 字符
- **类型注解**：关键函数添加类型注解
- **文档字符串**：公开函数需有 docstring

### 5.2 项目配置（根目录 `pyproject.toml`）

```toml
[project]
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
```

### 5.3 命名约定

| 类型 | 约定 | 示例 |
|:---|:---|:---|
| 文件名 | 小写下划线或中文 | `k_pattern.py`, `资金费率卡片.py` |
| 类名 | PascalCase | `KPattern`, `DataProvider` |
| 函数名 | snake_case | `compute_indicators()` |
| 常量 | UPPER_SNAKE | `MAX_WORKERS` |

### 5.4 错误处理

- 使用 `except Exception as e:` 捕获异常并记录日志
- 禁止裸 `except:`
- 关键操作添加超时处理

### 5.5 日志规范

```python
import logging
logger = logging.getLogger(__name__)

logger.info("操作成功: %s", detail)
logger.warning("警告: %s", message)
logger.error("错误: %s", error, exc_info=True)
```

---

## 6. Project Map（项目结构速览）

```
tradeagnt/                          # 仓库根（包名 tradecat）
├── .cursor/
│   ├── mcp.json                    # Linear MCP（项目级）
│   └── rules/linear-workflow.mdc   # Agent 任务跟踪规则
├── config/
│   ├── .env                        # 生产配置（不提交）
│   ├── .env.example
│   └── strategies/                 # YAML 策略 + current/ + releases/
├── src/tradecat/                   # ★ 主代码
│   ├── cli/                        # tradecat 子命令
│   ├── core/                       # 引擎：signals/indicators/providers/paper/backtest
│   ├── tui/                        # 终端看板
│   └── common/                     # 共享工具
├── tests/                          # pytest（pythonpath=src）
├── scripts/                        # init/start/verify、只读桥接、遗留 backtest.sh
├── libs/database/                  # SQLite 数据文件（signal/cooldown/paper）
├── docs/
│   ├── market-integration/         # 新市场接入
│   └── linear-mcp-setup.md         # Linear MCP 启用说明
├── .issues/                        # 本地 Issue 草稿（SSOT=Linear）
├── artifacts/                      # 回测/分析产物
├── pyproject.toml                  # 包定义 + ruff/pytest
├── Makefile
├── AGENTS.md                       # 本文档
└── README.md
```

> **无 `services/` 目录**：旧微服务文档若仍出现该路径，视为过期。

### 6.1 `core` 分层（逻辑边界）

```
src/tradecat/core/
├── providers/          # 行情/K 线（按市场插件）
├── indicators/         # 指标计算
├── signals/            # 策略 YAML + 规则引擎
├── paper_trading/      # 模拟盘
├── backtest/           # 回测
├── symbols/            # 标的归一化（crypto / us_stock）
└── connectors/         # 交易所连接器（可选）
```

### 6.2 TUI 三页结构

| 顶页 | 按键 | 子页 |
|:---|:---|:---|
| P1 行情 | `t` 切页；`1`/`2`/`[/]` | 加密 / 美股（`3`–`6` A股/港股/基金） |
| P2 模拟盘 | 同上子页 | 过滤持仓/成交；`t` 仅切大页 |
| P3 资讯 | `t` 切页 | 无数字键跳页 |

---

## 7. Common Pitfalls（常见坑与修复）

### 7.1 TA-Lib 安装失败

```bash
# 先安装系统库
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure --prefix=/usr && make && sudo make install
cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# 再安装 Python 包
pip install TA-Lib
```

### 7.2 数据库连接失败

```bash
# 检查端口（根据 config/.env 配置选择 5433 或 5434）
ss -tlnp | grep 5434

# 测试连接
PGPASSWORD=postgres psql -h localhost -p 5434 -U postgres -c "\l"
```

### 7.3 虚拟环境问题

```bash
# 重建根目录虚拟环境
rm -rf .venv
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 7.4 .env 权限问题

```bash
# 服务启动脚本要求 600 权限
chmod 600 config/.env
```

### 7.5 环境检查

```bash
# 部署前运行环境检查，确保所有依赖就绪
./scripts/check_env.sh

# 检查内容：
# - Python 版本 (3.10+)
# - pip/venv 可用性
# - 虚拟环境完整性
# - config/.env 配置
# - 数据库连接 (pg_isready)
# - 网络连接 (Telegram/Binance API)
# - 磁盘空间
```

### 7.6 日志轮转配置

```bash
# 1. 生成配置文件（替换路径占位符）
cd /path/to/tradecat
sed -e "s|{{PROJECT_ROOT}}|$(pwd)|g" \
    -e "s|{{USER}}|$(whoami)|g" \
    config/logrotate.conf > /tmp/tradecat-logrotate.conf

# 2. 手动执行轮转
sudo logrotate -f /tmp/tradecat-logrotate.conf

# 3. 安装到系统（可选，自动每日执行）
sudo cp /tmp/tradecat-logrotate.conf /etc/logrotate.d/tradecat

# 轮转策略：
# - 核心服务日志：每天或 50MB，保留 14 天
# - 预览服务日志：每天或 50MB，保留 7 天
# - 顶层 logs 目录日志：每天或 20MB，保留 7 天
```

### 7.7 守护进程模式

```bash
# 启动守护进程（自动重启崩溃的服务）
./scripts/start.sh daemon

# 停止守护进程和所有服务
./scripts/start.sh daemon-stop

# 守护策略：
# - 检查间隔：30 秒
# - 最大重试：5 次/5分钟窗口
# - 指数退避：10s → 20s → 40s → ... → 300s (最大)
# - 超过上限后暂停重启，告警写入 alerts.log
```

### 7.8 端口冲突（双库架构）

```bash
# 旧库（5433）：与早期数据采集链兼容
# 新库（5434）：多 schema 架构（raw/agg/quality），.env.example 与 export/compression 脚本默认值

# 确认当前使用端口
grep "DATABASE_URL" config/.env | grep -oP ':\K\d+(?=/)'

# 若需切换端口，需同步修改：
# - config/.env 中 DATABASE_URL
# - scripts/data/export_timescaledb.sh
# - scripts/data/timescaledb_compression.sh
# - README.md 中所有示例命令
```

### 7.8 端口冲突（双库架构）

```bash
# 旧库（5433）：与早期数据采集链兼容
# 新库（5434）：多 schema 架构（raw/agg/quality），.env.example 与 export/compression 脚本默认值

# 确认当前使用端口
grep "DATABASE_URL" config/.env | grep -oP ':\K\d+(?=/)'

# 若需切换端口，需同步修改：
# - config/.env 中 DATABASE_URL
# - scripts/data/export_timescaledb.sh
# - scripts/data/timescaledb_compression.sh
```

---

## 8. PR / Commit Rules（提交规则）

### 8.1 Commit Message 规范

```
<type>(<scope>): <subject>

<body>
```

**Type**：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `refactor`: 重构
- `chore`: 杂项
- `style`: 代码格式

**示例**：
```
feat(trading): 添加 K线形态检测指标
fix(telegram): 修复排行榜数据加载错误
docs: 更新 README 快速开始指南
chore: standardize project structure for all services
```

### 8.2 提交前检查清单

- [ ] 代码通过 `make lint`
- [ ] 测试通过 `make test`（如有）
- [ ] 相关文档已更新
- [ ] 配置变更已同步到 `config/.env.example`
- [ ] 新依赖已添加到 `requirements.txt` 并 `make lock`

### 8.3 CI 说明

CI（`.github/workflows/ci.yml`）仅执行：
- ruff 静态检查（忽略 E501, E402）
- py_compile 语法检查（前 50 个 .py 文件抽样）

完整测试需本地运行 `./scripts/verify.sh`。

---

## 9. Documentation Sync Rule（文档同步规则）

### 9.1 强制同步

以下变更**必须**同步更新文档：

| 变更类型 | 需更新的文档 |
|:---|:---|
| 新增/修改命令 | README.md, README_EN.md, AGENTS.md |
| 新增/修改配置项 | README.md, README_EN.md, `config/.env.example` |
| 新增/修改指标 | README.md (指标列表) |
| 目录结构变更 | README.md, README_EN.md, AGENTS.md |
| 新增/修改服务 | README.md, README_EN.md, AGENTS.md |

### 9.2 文档更新原则

- 以实时代码为唯一源头
- 不确定的端口、路径、命令**必须**验证后再写入
- 三份文档（README.md、README_EN.md、AGENTS.md）保持同步

---

## 10. 环境变量参考

所有配置集中在 `config/.env`，详细说明见 `config/.env.example`。

### 10.1 核心配置

| 变量 | 说明 | 示例 |
|:---|:---|:---|
| `DATABASE_URL` | TimescaleDB 连接串 | `postgresql://postgres:postgres@localhost:5434/market_data` |
| `BOT_TOKEN` | Telegram Bot Token | `123456:ABC...` |
| `HTTP_PROXY` | HTTP 代理 | `http://127.0.0.1:9910` |
| `DEFAULT_LOCALE` | 默认语言 | `en` |
| `SIGNAL_DATA_MAX_AGE` | 信号数据最大允许时长（秒，超限不触发） | `600` |
| `COOLDOWN_SECONDS` | 全局信号冷却（秒） | `300` |
| `LINEAR_API_KEY` | Linear MCP（API Key 方式，可选） | 见 `docs/linear-mcp-setup.md` |

### 10.2 TUI / 模拟盘（`tradecat tui`）

| 变量 | 说明 |
|:---|:---|
| `TUI_SIGNAL_STRATEGY` | 主策略 YAML（默认 `current/fast_1m.yaml`） |
| `TUI_SIGNAL_STRATEGY_EXTRA` | 第二策略（如 `us_fast_5m.yaml`） |
| `PAPER_AUTO_MARKET` | 跟单市场：`crypto` / `us_stock` / `all` |
| `TUI_SIGNAL_POLLER` | `0` 关闭后台信号轮询 |

### 10.3 币种管理（SYMBOLS_*）

| 变量 | 说明 |
|:---|:---|
| `SYMBOLS_GROUPS` | 使用的分组（main4/main6/main20/auto/all） |
| `SYMBOLS_GROUP_<name>` | 自定义分组定义（如 `SYMBOLS_GROUP_defi`） |
| `SYMBOLS_EXTRA` | 额外添加的币种 |
| `SYMBOLS_EXCLUDE` | 强制排除的币种 |

### 10.4 数据采集配置（遗留 env 名）

| 变量 | 服务 | 说明 |
|:---|:---|:---|
| `BACKFILL_MODE` | collector-service（legacy fallback） | 回填模式（all/days/none） |
| `BACKFILL_DAYS` | collector-service（legacy fallback） | 回填天数（BACKFILL_MODE=days 时生效） |
| `BACKFILL_START_DATE` | collector-service（legacy fallback） | 回填起始日期（可选） |
| `MAX_CONCURRENT` | collector-service（legacy fallback） | 最大并发请求数（默认 5） |
| `RATE_LIMIT_PER_MINUTE` | collector-service（legacy fallback） | 每分钟最大请求数（默认 1800） |
| `INTERVALS` | collector-service / trading-service | K线周期（逗号分隔） |
| `KLINE_INTERVALS` | collector-service（legacy fallback） | WebSocket 订阅周期 |
| `FUTURES_INTERVALS` | collector-service（legacy fallback） | 期货指标周期（最小 5m） |

### 10.5 服务配置（遗留 env 名）

| 变量 | 服务 | 说明 |
|:---|:---|:---|
| `MAX_WORKERS` | trading-service | 计算线程数 |
| `COMPUTE_BACKEND` | trading-service | 计算后端（thread/process/hybrid） |
| `HIGH_PRIORITY_TOP_N` | trading-service | auto 模式高优先级币种数量 |
| `MARKETS_SERVICE_DATABASE_URL` | collector-service（legacy fallback） | 旧数据库连接键，collector 会兼容读取 |
| `ALTERNATIVE_DB_SCHEMA` | collector-service / tui-service | 统一新闻表 schema（读写 `<ALTERNATIVE_DB_SCHEMA>.news_articles`，默认 `alternative`） |
| `CRYPTO_WRITE_MODE` | collector-service（legacy fallback） | 写入模式（raw/legacy） |
| `ORDER_BOOK_TICK_INTERVAL` | collector-service（legacy fallback） | L1 tick 采样间隔（秒，默认 1） |
| `ORDER_BOOK_FULL_INTERVAL` | collector-service（legacy fallback） | L2 full 采样间隔（秒，默认 5） |
| `ORDER_BOOK_DEPTH` | collector-service（legacy fallback） | 每侧档位数（默认 1000） |
| `ORDER_BOOK_RETENTION_DAYS` | collector-service（legacy fallback） | 数据保留天数（默认 30） |
| `NEWS_RSS_FEEDS` | collector-service / tui-service | 新闻源列表（支持 `direct://...` 与 RSS/Atom URL，逗号或换行分隔） |
| `NEWS_RSS_POLL_INTERVAL_SECONDS` | collector-service（legacy fallback） | 新闻采集轮询间隔（秒，默认 2） |
| `NEWS_RSS_LIMIT` | collector-service（legacy fallback） | 单轮最多入库文章数（默认 100） |
| `NEWS_RSS_WINDOW_HOURS` | collector-service（legacy fallback） | 新闻时间窗口（小时，默认 72） |
| `NEWS_RSS_TIMEOUT_SECONDS` | collector-service（legacy fallback） | RSS 抓取超时（秒，默认 20） |
| `NEWS_RETENTION_HOURS` | collector-service（legacy fallback） | 原始新闻保留小时数（默认 24；0=不自动清理） |
| `NEWS_RETENTION_CLEANUP_INTERVAL_SECONDS` | collector-service（legacy fallback） | 执行过期新闻清理的最小间隔（秒，默认 600） |
| `NEWS_RSS_FAILURE_THRESHOLD` | collector-service（legacy fallback） | 单个 RSS 源连续失败多少次后进入冷却（默认 2） |
| `NEWS_RSS_FAILURE_COOLDOWN_SECONDS` | collector-service（legacy fallback） | RSS 故障源冷却时长（秒，默认 300） |

---

## 11. 快速参考卡片

```bash
# 环境与验证
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/verify.sh
ruff check src/tradecat tests
pytest tests/ -q

# Linear MCP：Cursor Settings → MCP → 启用 linear（见 docs/linear-mcp-setup.md）

# 启动/停止（遗留脚本 + TUI）
./scripts/start.sh start|stop|status|run
tradecat tui

# 模块化 CLI
tradecat signal --config config/strategies/us_fast_5m.yaml --symbol NVDA
tradecat daemon --strategy current/fast_1m.yaml --auto-trade
tradecat paper status
tradecat backtest --strategy us_fast_5m.yaml --symbol NVDA --days 3

# TUI 双市场
TUI_SIGNAL_STRATEGY=current/fast_1m.yaml \
TUI_SIGNAL_STRATEGY_EXTRA=us_fast_5m.yaml \
PAPER_AUTO_MARKET=all \
tradecat tui

# Trade Agent 只读桥接命令
python scripts/tradecat_get_quotes.py NVDA
python scripts/tradecat_get_quotes.py --market crypto_spot BTC_USDT ETH_USDT
python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5
# 读取 <ALTERNATIVE_DB_SCHEMA>.news_articles（默认 alternative.news_articles）
python scripts/tradecat_get_news.py --symbol BTCUSDT --limit 5 --since-minutes 120
python3 scripts/tradecat_get_backtest_summary.py --run-id <run_id>

# 回测（推荐模块化 CLI）
tradecat backtest --strategy config/strategies/fast_1m.yaml --symbol BTC_USDT --days 7
# 遗留脚本（可选）
./scripts/backtest.sh
# 覆盖率检查（仅检查，不执行）
./scripts/backtest.sh --check-only --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# 覆盖不足时可切离线回放（不依赖 signal_history 覆盖）
./scripts/backtest.sh --mode offline_replay --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# SQLite 129规则离线重放（基于指标表历史行；timeframe=1m 时默认规则周期自动按 1m 对齐）
./scripts/backtest.sh --mode offline_rule_replay --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# 历史信号 vs 129规则重放对比（生成 comparison.json/.md + missing规则未命中原因诊断；默认不受 signal days/count 门槛限制）
./scripts/backtest.sh --mode compare_history_rule --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# 对齐 gate（适合本地检查 / CI；未达标返回退出码 2）
./scripts/backtest.sh --mode compare_history_rule --alignment-min-score 70 --alignment-max-risk-level medium --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# 覆盖率门槛（默认可不写；需要强行跑可加 --force）
./scripts/backtest.sh --check-only --min-signal-days 7 --min-signal-count 200 --min-candle-coverage-pct 95
# 资金口径覆盖（本金/杠杆/仓位）
./scripts/backtest.sh --symbols BTCUSDT,ETHUSDT --initial-equity 3000 --leverage 2 --position-size-pct 0.2
# BTC/ETH 保守模板（阈值 200/200）
./scripts/backtest.sh --config src/backtest/strategies/default.crypto.btc_eth.safe.yaml
# Walk-Forward（滚动窗口）
./scripts/backtest.sh --walk-forward --wf-train-days 7 --wf-test-days 3 --wf-step-days 3 --walk-forward-max-folds 6 --symbols BTCUSDT,ETHUSDT --start "2026-01-14 00:00:00" --end "2026-02-13 00:00:00"
# 产物会在 walk_forward_summary.json / metrics.json 记录每折 selected_params（默认先做 train window 轻量选参）
# 真实窗口校准闭环（PG 恢复后执行；未恢复可先 --dry-run）
./scripts/backtest/real_window_validation.sh --dry-run
# issue 回填草稿提取（校准完成后使用；若要直接写回 issue，可加 --apply-issues）
python3 scripts/backtest/backtest_issue_fill.py --run-prefix <run_prefix> --print
# 分层滑点：strategy YAML 可设置 execution.slippage_model=layered，并用 slippage_max_bps / slippage_*_weight / slippage_volume_window 控制动态滑点
# 执行约束：strategy YAML 可设置 max_bar_participation_rate / min_order_notional / impact_bps_per_bar_participation，产物会输出 partial_fill / fill_ratio / impact_cost
# 多基准对比：metrics/report/walk_forward_summary 会额外输出 buy_hold / risk_parity / momentum 三类基准收益，以及 excess_return_vs_* / best_baseline_name

# 数据库（根据实际端口选择 5433 或 5434）
PGPASSWORD=postgres psql -h localhost -p 5434 -U postgres -d market_data
sqlite3 libs/database/services/telegram-service/market_data.db

# 备份
./scripts/data/export_timescaledb.sh
```

---

## 12. 变更日志

- 2026-05-23: Linear 清理（项目 TradeCat v0.8 / 归档 008 & tradeagent；`area:*` 标签）；`docs/linear-issue-spec.md` 规则驱动 Issue 规范。
- 2026-05-23: `AGENTS.md` 对齐模块化单体（`src/tradecat`）；新增 Linear MCP（`.cursor/mcp.json`、`docs/linear-mcp-setup.md`）；`verify.sh` 改为检查 `src/tradecat`。
- 2026-01-28: 新增信号相关性分析脚本与文档，输出分析产物目录。
- 2026-01-29: 新增宣传材料与比赛汇报材料文档。
- 2026-01-29: Tradecat Preview API 新增 `/api/futures/base-data`（直读 SQLite 基础数据）。
