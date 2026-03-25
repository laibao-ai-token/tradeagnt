# 仓库清理执行手册

> 最后更新: 2026-03-24
> 适用范围: TradeCat 主仓工作区冗余目录、运行产物、环境副产物的低风险治理
> 核实状态: 已结合 `002-repository-hygiene-audit.md`、`004-service-review-sequence.md`、`AGENTS.md` 约束核实
> 总体结论: 当前适合先做低风险归档与可重建目录治理，不适合直接做大规模删除

---

## 目标

本手册的目标不是“尽快删干净”，而是让仓库清理动作满足三个条件：

1. 不误伤业务数据资产
2. 不破坏当前本机开发与运行
3. 清理前后都可验证

## 清理原则

### 原则 1：先分层，再动手

任何清理动作都必须先回答：

1. 这是业务数据吗
2. 这是运行产物吗
3. 这是可重建环境吗
4. 这是外挂仓吗

### 原则 2：先归档规则，再做删除

当前更适合先形成稳定规则：

- 哪些必须保留
- 哪些只能归档
- 哪些确认后可清

而不是先执行批量删除。

### 原则 3：清理动作与业务改动分开

目录清理、日志轮转、外挂仓治理，不应和业务代码提交混在一起。  
否则 `git status` 和 review 都会失焦。

## 禁止触碰

以下路径不属于清理对象：

| 路径 | 原因 |
|:---|:---|
| `config/.env` | 生产配置，只读 |
| `libs/database/services/telegram-service/market_data.db` | 业务 SQLite 数据 |
| `libs/database/services/signal-service/cooldown.db` | 冷却持久化数据 |
| `libs/database/services/signal-service/signal_history.db` | 信号历史数据 |
| `libs/database/csv/` | 本地主数据资产 |
| `backups/timescaledb/` | 备份目录，如出现按敏感资产处理 |

规则：

- 不删除
- 不移动
- 不做“顺手整理”

## 可保留但应建立策略

这些目录不是源码主体，但有保留价值：

| 路径 | 当前处理建议 |
|:---|:---|
| `artifacts/backtest/` | 按 run 保留，避免无限增长 |
| `artifacts/indicator_db/` | 建立归档周期 |
| `artifacts/analysis/` | 体积小，可保留 |
| `logs/` | 轮转或按日期归档 |
| `services/*/logs` | 轮转或按服务归档 |

建议：

- 不把它们当“垃圾”直接删
- 先明确保留期限
- 产物保留策略单独成文，而不是随手处理

## 可归档对象

这些内容更适合移出主视野，而不是长期停在当前工作区根部：

| 路径 | 建议 |
|:---|:---|
| `repository/*` 中仅作参考/联调的子仓 | 建立长期保留名单，其余归档或单独管理 |
| `local-issue.zip` | 归档或删除 |
| 一次性导出包、历史性手工归档文件 | 统一移到专门归档位置 |

判断标准：

- 不是主仓业务代码
- 不是当前必须运行依赖
- 不是主仓长期 Source of Truth

## 可重建清理对象

这些目录理论上都能重建，但清理前必须先确认恢复路径：

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
- `repository/opencli/node_modules`
- `repository/longbridge-terminal/target`
- `repository/ESPRIT/TradingAgents/.venv`

### 小型副产物

- `libs/tradecat_common.egg-info`

规则：

- 当前先登记，不直接删
- 清理前必须知道如何恢复
- 清理后必须跑最小验证命令

## 清理前检查

在任何清理动作前，先执行以下检查：

### 1. 记录当前状态

```bash
git status --short
du -sh services services-preview scripts libs artifacts logs repository 2>/dev/null
```

### 2. 确认敏感资产存在

```bash
test -f config/.env && echo "env:ok"
test -f libs/database/services/telegram-service/market_data.db && echo "market_data:ok"
test -f libs/database/services/signal-service/cooldown.db && echo "cooldown:ok"
test -f libs/database/services/signal-service/signal_history.db && echo "signal_history:ok"
test -d libs/database/csv && echo "csv:ok"
```

### 3. 确认环境可恢复

对于准备清理的 `.venv` / `node_modules` / `target`，先确认至少存在以下一种恢复方式：

- `make venv && make install`
- `./scripts/init.sh <service>`
- `npm install` / `pnpm install`
- `cargo build`

如果恢复命令不明确，就先不要清。

## 清理后验证

清理后至少执行以下最小验证：

### 1. 桥接层验证

```bash
python3 scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 1
python3 scripts/tradecat_get_backtest_summary.py --run-id latest
```

说明：

- 第二条如果 `latest` 不命中，不一定表示损坏；应改为明确 `run_id` 再核实

### 2. 主流程入口验证

```bash
./scripts/start.sh run --help >/dev/null 2>&1 || true
./scripts/start.sh status
```

### 3. 关键测试验证

```bash
pytest -q tests/test_tradecat_get_backtest_summary.py
pytest -q services/data-service/tests/test_collection_pipeline.py
cd services-preview/tui-service && pytest -q tests/test_db.py tests/test_news_db.py
```

### 4. 语法验证

```bash
python3 -m py_compile scripts/tradecat_get_signals.py scripts/tradecat_get_news.py scripts/tradecat_get_backtest_summary.py
```

## 建议清理顺序

### Phase 1: 立即可做的低风险清理

优先级：

1. `local-issue.zip`
2. `libs/tradecat_common.egg-info`
3. 顶层 `logs/`
4. 各服务 `logs/`

特点：

- 不涉及业务数据
- 不涉及主仓核心代码
- 失败影响小

### Phase 2: 条件满足后再做的可重建目录清理

优先级：

1. 单个服务 `.venv`
2. 单个外挂仓 `node_modules`
3. 单个 Rust `target`

特点：

- 节省空间明显
- 但必须有恢复命令和验证动作

### Phase 3: 外挂仓治理

目标不是删除，而是明确：

1. 哪些外挂仓长期保留
2. 哪些只是联调副本
3. 哪些应该移出当前主仓工作区

建议先出名单，再动目录。

## 不建议当前就做的事

当前不建议：

- 批量删除所有 `.venv`
- 批量删除所有 `node_modules`
- 直接清空 `artifacts/`
- 直接清空 `logs/` 而不做保留策略
- 处理脏的嵌套仓历史
- 顺手改 `.gitignore` 来掩盖问题

原因：

- 当前工作区还有其他未提交变更
- 仓库边界刚理清，还没有形成统一清理口径
- 大规模删除会让后续问题定位更难

## 当前最推荐的最小执行包

如果现在只做一轮最小清理，推荐只做这四项：

1. 处理 `local-issue.zip`
2. 处理 `libs/tradecat_common.egg-info`
3. 整理顶层与服务日志
4. 明确外挂仓长期保留名单

这样可以先降低噪音，但不会破坏运行环境。

## 与后续 review 的关系

这份手册不是为了替代代码 review，而是为了让代码 review 更聚焦。

预期顺序应是：

1. 先完成仓库级基线文档 `001-005`
2. 再按 [004-service-review-sequence.md](/public/home/lixh6/laibao/proj/tx_test_0106/tradecat-origin/.issues/open/review/000-repo-review/004-service-review-sequence.md) 开始第一轮真正的代码 review

## 下一步执行建议

现在 `000-repo-review` 的基线文档已经齐了。  
下一步建议不要再补框架文档，而是直接开始 Phase 1：对 `scripts/` + `scripts/lib/` 做第一轮代码 review。
