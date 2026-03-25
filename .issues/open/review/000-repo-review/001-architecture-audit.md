# TradeCat 仓库架构审计

> 最后更新: 2026-03-24
> 审计范围: 仓库结构 / 服务边界 / 数据存储 / 运行入口 / review 推进顺序
> 核实状态: 已通过目录结构、脚本入口、Issue 规划文档核实
> 总体结论: 需整改，但不建议先做全仓逐文件 code review

---

## 审计摘要

当前 `TradeCat` 主仓的核心业务链路其实已经存在清晰边界：

- `services/` 负责核心链路
- `services-preview/` 负责预览链路
- `scripts/` 负责统一入口与只读桥接
- `libs/` 负责共享库与本地数据库

真正的问题不在“完全没有架构”，而在“仓库工作区边界混在一起”：

1. 主仓源码、预览服务、外挂仓、运行产物、本地 issue、临时依赖同时出现在同一个工作区
2. `repository/*` 下有多个嵌套仓，容易让 review 范围失焦
3. `.venv`、`logs`、`artifacts`、本地 zip/egg-info 等运行产物会放大噪音
4. 当前最需要的是先建立一份边界清单，再按区域 review，而不是直接全仓逐文件审查

结论：

- 可以继续推进架构治理
- 不建议直接发起“整仓 code review”
- 建议推进顺序为：
  1. 仓库架构盘点
  2. 仓库卫生清单
  3. `#007` 目标架构对齐
  4. 按服务分区 review

## 仓库结构盘点

| 路径 | 角色 | 当前判断 |
|:---|:---|:---|
| `config/` | 全局配置 | 主仓核心组成，`config/.env` 只读 |
| `scripts/` | 顶层启动、校验、只读桥接脚本 | 主仓核心组成 |
| `services/` | 核心服务：`data-service` / `trading-service` / `signal-service` | 主仓核心组成 |
| `services-preview/` | 预览服务：`markets-service` / `tui-service` | 主仓核心组成，但需与正式链路明确边界 |
| `libs/common/` | 共享库 | 主仓核心组成 |
| `libs/database/` | 本地数据库、CSV、DDL | 主仓数据资产，敏感且应只读对待 |
| `docs/` | 长期文档 | 主仓组成 |
| `.issues/` | 本地 issue 与推进文档 | 主仓的治理层，不属于运行时 |
| `artifacts/` | 回测、分析、覆盖率等产物 | 运行产物，不应和架构源码混为一谈 |
| `logs/` / `run/` / `cache/` | 运行态目录 | 运行产物 |
| `repository/*` | 外部仓、参考实现、工具链 | 外挂工作区，不应默认视为主仓业务代码 |
| `skills/` | 本地技能与桥接能力 | 辅助能力层 |

## 主仓应承担什么

主仓的合理职责应收敛为以下几层：

1. 数据采集与整理
2. 指标计算与规则信号
3. 回测、校准、只读查询
4. TUI 展示与工作台接入
5. 文档、issue、runbook、脚本化运维

不建议把以下内容继续混入主仓的“默认 review 范围”：

- `repository/*` 外部仓实现细节
- 各服务 `.venv`
- 大量 `logs/`
- 临时压缩包、`egg-info`、一次性归档目录

## 服务边界与职责一致性

| 服务 | 位置 | 应负责 | 不应负责 | 当前判断 |
|:---|:---|:---|:---|:---|
| `data-service` | `services/data-service` | 加密货币行情采集、回填、入库 | 指标计算、UI | 边界基本清晰 |
| `trading-service` | `services/trading-service` | 技术指标计算、结果写入 SQLite | 推送、TUI 展示 | 边界基本清晰 |
| `signal-service` | `services/signal-service` | 规则信号、冷却、回测链路 | UI 写入、展示逻辑 | 边界基本清晰 |
| `markets-service` | `services-preview/markets-service` | 全市场采集、新闻抓取 | 指标计算、交易执行 | 预览链路，需与正式链路保持清晰接口 |
| `tui-service` | `services-preview/tui-service` | 只读展示、工作台入口 | 写库、推送、交易执行 | 边界基本清晰 |

判断：

- 服务级架构本身没有失控
- 当前混乱主要发生在“仓库级工作区边界”，不是“服务内部完全失序”

## 数据存储与状态文件

当前存在三类数据资产，性质不同：

### 1. 业务数据资产

- `libs/database/services/telegram-service/market_data.db`
- `libs/database/services/signal-service/cooldown.db`
- `libs/database/services/signal-service/signal_history.db`
- `libs/database/csv/`

这些属于主仓的重要只读/持久化资产，不应被“清理仓库”动作误删。

### 2. 运行产物

- `artifacts/backtest/`
- `artifacts/analysis/`
- `logs/`
- `services/*/logs`

这些对验证有价值，但不应与“长期源码结构”混为一类。

### 3. 环境与依赖副产物

- `services/*/.venv`
- `services-preview/*/.venv`
- `repository/*/node_modules`
- `repository/*/target`
- `libs/tradecat_common.egg-info`
- `local-issue.zip`

这些不属于架构主体，但会显著放大仓库体积和 review 噪音。

## 当前最容易让 review 失焦的点

### 1. 主仓与外挂仓边界不清

`repository/` 下同时存在 `openclaw`、`OpenAlice`、`tradecat-upstream`、`symphony`、`worldmonitor` 等多个仓。  
如果不先划清边界，review 很容易从 `TradeCat` 主线滑到参考实现、第三方工具或实验目录。

### 2. 运行态目录与源码目录混放

每个服务目录下同时存在 `src/`、`tests/`、`.venv/`、`logs/`。  
源码 review 本该聚焦 `src/`、`tests/`、关键脚本，但实际很容易被环境目录干扰。

### 3. 治理文档与业务代码并行推进，但缺少统一索引

`.issues/open/review/`、`.issues/open/007-trading-system/`、`docs/`、`README*` 都在承载架构信息。  
这说明治理在推进，但也意味着“架构 Source of Truth” 需要进一步收束。

### 4. 目标架构已经提出，但落地路径仍需对齐

`#007` 已经提出 “TradeCat 主仓 + Bridge / Domain Layer + 外部消费层” 的目标形态。  
接下来应先把“主仓当前能力”和“#007 目标能力”建立映射，再进入实现。

## `repository/*` 的建议定位

`repository/*` 更适合作为以下三类内容的集合，而不是主仓默认的一部分：

1. 外部参考实现
2. 辅助工具仓
3. 联调或工作台依赖

治理建议：

- 主仓 review 默认不覆盖 `repository/*`
- 只有在明确讨论外部编排层、`symphony`、`OpenAlice` 集成时，才点状纳入
- 文档中应把“主仓代码”与“外挂仓/参考仓”分栏说明

## 与 `#007` 的关系

`#007` 的目标不是重写主仓，而是在现有能力之上补齐交易系统运行层：

- `TradeCat` 继续做数据、指标、信号、回测、TUI
- 外部编排层只消费稳定命令与领域对象
- 中间新增 `Bridge / Domain Layer`

这意味着当前推进重点不应是“大重构”，而应是：

1. 先确认主仓的现状边界
2. 再把 `#007` 子任务映射到现有模块
3. 最后按子任务落地

## 建议推进顺序

### Phase 1: 架构盘点

- 产出一份仓库结构与边界清单
- 明确什么属于主仓、什么属于外挂仓、什么属于运行产物
- 作为后续 review 的前置基线

### Phase 2: 仓库卫生清单

- 识别 `.venv`、`node_modules`、`logs`、zip、`egg-info` 等噪音项
- 只先做清单和处理建议
- 未经明确确认，不删除数据或环境

### Phase 3: `#007` 架构对齐

- 将 `#007-01` 至 `#007-05` 与现有主仓模块一一对应
- 判断哪些可以直接复用，哪些需要新增桥接层

### Phase 4: 按服务 review

建议顺序：

1. `signal-service`
2. `trading-service`
3. `data-service`
4. `markets-service`
5. `tui-service`

原因：

- `signal-service` 与回测、规则、交易判断最接近
- `trading-service` 是信号输入上游
- `data-service` 和 `markets-service` 偏数据采集
- `tui-service` 更适合在核心链路清楚后做展示层 review

## 关键文件引用

- `AGENTS.md`
- `.issues/open/007-trading-system/007-feature-trade-agent-trading-system-runbook.md`
- `.issues/templates/architecture.md`
- `scripts/start.sh`
- `scripts/tradecat_get_quotes.py`
- `scripts/tradecat_get_signals.py`
- `scripts/tradecat_get_news.py`
- `scripts/tradecat_get_backtest_summary.py`

## 待确认问题

1. `repository/*` 中哪些仓需要长期保留在当前工作区，哪些只是临时联调副本
2. `docs/`、`.issues/`、`README*` 之间哪一处应作为长期架构说明的唯一主索引
3. `#007` 的桥接层是优先落在主仓脚本层、共享库层，还是单独形成新模块

## 下一步执行建议

如果继续推进，建议直接开始第二步：在 `.issues/templates/` 或 `.issues/open/007-trading-system/` 下补一份“仓库卫生清单”，把当前冗余目录、可归档目录、不可触碰的数据资产分开列清楚。
