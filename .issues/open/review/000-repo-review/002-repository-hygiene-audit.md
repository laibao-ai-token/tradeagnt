# TradeCat 仓库卫生审计

> 最后更新: 2026-03-24
> 审计范围: 冗余目录 / 运行产物 / 环境副产物 / Git 噪音 / 数据资产保护
> 核实状态: 已通过当前工作区目录、体积、`git status` 核实
> 总体结论: 存在明显噪音，但应先分类治理，不应直接做删除式清理

---

## 审计摘要

当前仓库的“卫生问题”主要不是源码本身，而是工作区同时承载了：

1. 主仓业务代码
2. 外挂仓与参考仓
3. 服务级虚拟环境
4. 构建产物与日志
5. 本地 issue、压缩包、`egg-info` 等一次性副产物

这会直接带来三个问题：

- `git status` 噪音大，难以判断真正需要提交的内容
- 仓库体积膨胀，review 容易失焦
- “业务数据资产”和“可重建环境目录”容易被误判成同一类

结论：

- 现在适合先做卫生分级
- 不适合直接删目录
- 下一步应按“禁止触碰 / 建议保留 / 建议归档 / 可重建清理”四类处理

## 当前体积热点

### 1. 服务虚拟环境

| 路径 | 当前体积 | 判断 |
|:---|:---|:---|
| `services-preview/markets-service/.venv` | `669M` | 可重建环境目录 |
| `services/trading-service/.venv` | `299M` | 可重建环境目录 |
| `services/data-service/.venv` | `147M` | 可重建环境目录 |
| `services/signal-service/.venv` | `35M` | 可重建环境目录 |
| `services-preview/tui-service/.venv` | `15M` | 可重建环境目录 |

### 2. 外挂仓构建/依赖目录

| 路径 | 当前体积 | 判断 |
|:---|:---|:---|
| `repository/longbridge-terminal/target` | `2.0G` | Rust 构建产物，可重建 |
| `repository/openclaw/node_modules` | `1.4G` | Node 依赖目录，可重建 |
| `repository/worldmonitor/node_modules` | `1.3G` | Node 依赖目录，可重建 |
| `repository/gstack/node_modules` | `18M` | Node 依赖目录，可重建 |

### 3. 主仓数据与产物

| 路径 | 当前体积 | 判断 |
|:---|:---|:---|
| `libs/database/csv` | `587M` | 业务数据资产，不能按冗余直接清理 |
| `artifacts/indicator_db` | `172M` | 分析/验证产物，需按保留策略管理 |
| `artifacts/backtest` | `72M` | 回测产物，需按 run 保留策略管理 |
| `libs/database/services/signal-service/signal_history.db` | `13M` | 业务历史数据，保留 |
| `logs` | `2.2M` | 顶层运行日志，可轮转/归档 |
| `artifacts/analysis` | `100K` | 小体积分析产物 |
| `libs/database/services/signal-service/cooldown.db` | `100K` | 业务状态数据，保留 |

### 4. 小型工作区杂物

| 路径 | 当前体积 | 判断 |
|:---|:---|:---|
| `local-issue.zip` | `7.0K` | 一次性压缩包，可归档或删除 |
| `libs/tradecat_common.egg-info` | `10K` | 打包副产物，可重建 |

## 禁止触碰的数据资产

以下内容不应被“清理冗余”动作直接处理：

| 路径 | 原因 |
|:---|:---|
| `config/.env` | 生产配置，只读 |
| `libs/database/services/telegram-service/market_data.db` | 业务 SQLite 数据 |
| `libs/database/services/signal-service/cooldown.db` | 信号冷却持久化数据 |
| `libs/database/services/signal-service/signal_history.db` | 信号触发历史 |
| `libs/database/csv/` | 本地主数据资产 |

说明：

- `AGENTS.md` 中提到的 `backups/timescaledb/` 在当前工作区未发现，但如果后续出现，也应按敏感备份目录处理

## 可重建目录

这些目录通常不应作为“仓库长期资产”来管理，但在当前机器上可能对运行仍有价值：

### 服务级环境

- `services/data-service/.venv`
- `services/trading-service/.venv`
- `services/signal-service/.venv`
- `services-preview/markets-service/.venv`
- `services-preview/tui-service/.venv`

### 外挂仓依赖/构建目录

- `repository/openclaw/node_modules`
- `repository/worldmonitor/node_modules`
- `repository/gstack/node_modules`
- `repository/longbridge-terminal/target`
- `repository/ESPRIT/TradingAgents/.venv`

处理原则：

- 当前先登记，不删除
- 只有在确认不影响本机开发后，才按目录类型批量清理
- 清理前应先确认对应项目可通过标准安装流程恢复

## 运行产物与日志目录

这些目录不属于长期源码资产，但对排障和验证可能有短期价值：

| 路径 | 性质 | 建议 |
|:---|:---|:---|
| `logs/` | 顶层运行日志 | 可轮转，可按日期归档 |
| `services/*/logs` | 服务日志 | 可轮转，可按服务归档 |
| `artifacts/backtest/` | 回测输出 | 应按 run 保留，不建议无限增长 |
| `artifacts/analysis/` | 分析输出 | 小体积，可保留 |
| `artifacts/indicator_db/` | 指标分析产物 | 建议建立保留策略或归档策略 |

## 当前 Git 噪音来源

从当前工作区看，Git 噪音主要来自四类：

### 1. 业务变更与治理文档混在一起

当前 `git status` 同时出现：

- `README.md`
- `README_EN.md`
- `AGENTS.md`
- `scripts/start.sh`
- `.issues/open/*`
- `.issues/templates/*`

这会让“业务改动”和“治理/文档改动”同时出现在一个视图里，降低可读性。

### 2. 外挂仓整体以未跟踪目录出现

当前未跟踪目录中包含：

- `repository/CLIProxyAPI/`
- `repository/ESPRIT/`
- `repository/chatgpt_register_v2_by_AI/`
- `repository/gstack/`
- `repository/opencli/`
- `repository/symphony/`
- `repository/worldmonitor/`

如果这些仓是联调用途，建议单独归档规则或单独管理，不应默认和主仓业务改动一起看。

### 3. 一次性副产物进入状态视图

- `local-issue.zip`
- `libs/tradecat_common.egg-info/`

这类内容应尽量避免长期停留在工作区根部。

### 4. Issue 迁移与归档动作会放大 diff 体积

当前 `.issues/open/006-backtest/` 与 `.issues/closed/006-backtest/` 同时存在移动/删除痕迹。  
这类治理动作本身合理，但最好与业务代码改动解耦提交。

## 分类处理建议

### A. 禁止直接清理

- `config/.env`
- `libs/database/` 下业务数据
- 任何仍在作为 Source of Truth 使用的 issue 文档

### B. 建议保留但建立策略

- `artifacts/backtest/`
- `artifacts/indicator_db/`
- `logs/`
- `services/*/logs`

建议：

- 建立按日期、按 run 的保留期限
- 明确哪些产物用于长期追溯，哪些只用于短期调试

### C. 建议归档或移出主视野

- `repository/*` 中仅作参考或联调的子仓
- `local-issue.zip`
- 历史性、一次性的导出包或归档文件

建议：

- 明确“长期保留在当前 workspace 的外挂仓名单”
- 其余目录按用途归档到专门位置，而不是长期停在主仓根下

### D. 确认后可重建清理

- `services/*/.venv`
- `services-preview/*/.venv`
- `repository/*/node_modules`
- `repository/*/target`
- `libs/tradecat_common.egg-info`

建议：

- 先补一份恢复命令索引
- 再决定是否做本机清理

## 建议推进顺序

### Phase 1: 先定保护边界

- 明确哪些路径属于不可删除数据资产
- 明确哪些路径虽然大，但只是可重建环境

### Phase 2: 先做规则，不做删除

- 形成一份“保留 / 归档 / 可清理”的分类表
- 先让团队对口径达成一致

### Phase 3: 再做低风险清理

优先级建议：

1. `local-issue.zip`
2. `libs/tradecat_common.egg-info`
3. 顶层和服务日志轮转
4. 可重建依赖目录

### Phase 4: 最后处理外挂仓治理

- 明确 `repository/*` 的长期保留名单
- 区分参考仓、联调仓、工作台依赖仓

## 下一步执行建议

如果继续推进，建议下一步不要直接清理目录，而是先做第三步：把 [`.issues/open/007-trading-system/007-feature-trade-agent-trading-system-runbook.md`](/public/home/lixh6/laibao/proj/tx_test_0106/tradecat-origin/.issues/open/007-trading-system/007-feature-trade-agent-trading-system-runbook.md) 里的目标架构，与当前主仓的真实模块做一张映射表。
