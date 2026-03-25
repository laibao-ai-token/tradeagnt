# Signal Service 域内核承接能力审查

> 最后更新: 2026-03-25
> 适用范围: `services/signal-service` 是否适合作为交易域主承接层的定点 review
> 当前状态: review
> 总体结论: `signal-service` 已经具备“信号域主承接层”的雏形，但还不具备在当前结构上直接承接 `risk / paper / execution` 三类有状态能力的自然边界

---

## 目标

这张单是 review-only，不要求改代码。  
目标是回答一个问题：

`signal-service` 现在是否已经具备成为 TradeCat 交易域主承接层的自然边界？

## 写入边界

只允许修改：

- 本 issue 文件

不要修改：

- 任何业务代码
- README / AGENTS / 其他 issue

## 重点核查文件

- `services/signal-service/src/__main__.py`
- `services/signal-service/src/storage/read_only.py`
- `services/signal-service/src/storage/cooldown.py`
- `services/signal-service/src/engines/pg_engine.py`
- `services/signal-service/src/engines/sqlite_engine.py`
- `services/signal-service/src/backtest/`

## 需要回答的问题

1. 当前哪些模块已经像“域内核”
2. 当前哪些模块只是历史实现，不适合继续扩
3. 如果后续新增 `risk/`、`paper_trading/`、`execution_protocol/`，最自然的落点分别在哪里
4. 当前最大的结构性阻碍是什么
5. 是否存在明显的大文件或多职责模块，后续需要拆

## 建议命令

```bash
rg -n "class |def " services/signal-service/src/engines/pg_engine.py
rg -n "class |def " services/signal-service/src/storage services/signal-service/src/backtest
wc -l services/signal-service/src/engines/pg_engine.py
```

## 完成标准

- 本文件形成可直接指导后续实现落位的 review 结论
- 明确写出“适合继续长的地方”和“不应继续长的地方”
- 不做代码改动

## Findings

1. `P0` 当前并不存在独立的“交易域应用层”，实际主承接层是引擎文件本身，而不是一个清晰的 domain core。`src/__main__.py:20-134` 只是把 `SQLite` / `PG` 两个 engine 线程拉起；`src/engines/pg_engine.py:987-1508` 同时承担配置加载、连库、取数、规则计算、冷却、历史写入、事件发布、循环控制和单例生命周期；`src/engines/sqlite_engine.py:59-498` 也是同一路径。如果把 `risk / paper_trading / execution_protocol` 继续塞进这里，新增状态机会直接绑定在轮询检测周期、freshness 判定和历史落盘副作用上，边界会继续恶化。
2. `P0` 最接近“交易域内核”的状态模型其实已经出现在 `backtest/`，但它被封在离线回测上下文里。`src/backtest/models.py:9-197` 已有 `ExecutionConfig`、`RiskConfig`、`Position`、`Trade` 等核心对象；`src/backtest/execution_engine.py:313-790` 已经实现了开平仓、杠杆、funding、liquidation、partial fill、impact、neutral close 等完整状态迁移；`src/backtest/runner.py:403-615` 再把这些能力接进回测流水线。结论不是“signal-service 没有交易语义”，而是“交易语义已经存在，但当前落在 backtest 子树里，不是 live domain 的自然宿主”。
3. `P1` `storage/` 只有一部分适合继续作为基础设施保留。`src/storage/read_only.py:18-126` 是干净的 read model，`src/storage/cooldown.py:28-92` 是小而内聚的 idempotency / cooldown adapter；但 `src/storage/history.py:71-352` 同时做对象归一化、写入、查询、统计、cleanup、展示格式化，`src/storage/subscription.py:26-148` 则是 user/table 订阅偏好存储。这两类模块都更像历史交付实现，不应该继续长成订单、仓位或风控状态中心。
4. `P1` 当前缺少统一的 canonical domain contract。线上有 `PGSignal`（`src/engines/pg_engine.py:39-51`）和 `events.SignalEvent`（`src/events/types.py:10-87`），离线又有一份 `backtest.models.SignalEvent`（`src/backtest/models.py:104-119`），历史层再用 duck typing 去兜底归一化（`src/storage/history.py:101-156`）。这意味着一旦新增 execution intent / fill / position snapshot，很容易继续复制“同名不同义”的 DTO，最终让 storage 和 reporting 被迫理解多种 shape。
5. `P2` 已经出现多处明显的大文件 / 多职责模块，后续如果不先拆，扩域成本会迅速上升。最突出的是 `src/engines/pg_engine.py`（1508 行）；其次是 `src/backtest/reporter.py`（1169 行）、`src/backtest/comparison.py`（1090 行）、`src/backtest/walkforward.py`（966 行）、`src/backtest/execution_engine.py`（790 行）、`src/backtest/precheck.py`（692 行）、`src/backtest/runner.py`（615 行）、`src/backtest/__main__.py`（534 行）。其中 `pg_engine.py` 是当前最大的结构性阻碍，`reporter/comparison/walkforward` 则是后续认知负担最高的分析层堆积点。

## Candidate Module Map

| 模块 | 当前角色判断 | 是否适合继续长 | 建议 |
|---|---|---|---|
| `src/rules/base.py:130-259` + `src/rules/__init__.py:29-138` | 规则定义、稳定 `rule_id`、按表/分类索引的信号策略注册表 | 是，但只限信号策略域 | 继续作为 signal policy registry，不要让它长出订单状态、仓位状态或执行副作用 |
| `src/events/types.py:10-87` + `src/events/publisher.py:18-149` | 信号事件契约 + 发布/订阅总线 | 有条件地是 | 适合作为“上游 signal intent 的 transport seam”；但执行相关 contract 不应继续塞进 `SignalEvent.extra` |
| `src/storage/cooldown.py:28-92` | 幂等 / 冷却适配器 | 是，作为基础设施 | 保持为低层 adapter，只负责 cooldown / idempotency，不承接交易真状态 |
| `src/storage/read_only.py:18-126` | 只读查询模型 | 是，作为 read model | 继续服务 TUI / bridge / QA / audit 查询，不做写入真源 |
| `src/engines/sqlite_engine.py:59-498` | 基于指标 SQLite 的历史信号扫描 runtime | 否 | 归类为 legacy runtime adapter，只做维护，不应承接新状态能力 |
| `src/engines/pg_engine.py:987-1508` | PG runtime 主引擎，当前把检测与副作用都揉在一起 | 否 | 先拆成 query adapter / rule evaluator / orchestration service；未拆前不应继续扩域 |
| `src/storage/history.py:71-352` | append-only 历史、统计、展示工具 | 否 | 定位为 audit sink，不要把它当订单/仓位的 canonical store |
| `src/storage/subscription.py:26-148` | 用户订阅偏好 | 否 | 明确留在 delivery edge；和交易域主承接层解耦 |
| `src/backtest/models.py:9-197` | 已成型的 execution / risk / position / trade 语义模型 | 是，但需要抽取 | 这是未来 live domain core 的最佳提炼源，不应永远埋在 `backtest/` 下面 |
| `src/backtest/execution_engine.py:313-790` | 交易状态迁移、费用、滑点、清算、容量约束 | 是，但需要抽取 | 这里是 `risk` / `paper_trading` / `execution_protocol` 的真实语义种子，但最终落点不应继续停在回测包内 |
| `src/backtest/runner.py:403-615` + `src/backtest/__main__.py:156-534` | CLI / artifact / mode orchestration | 否 | 保持为 backtest shell；未来应消费共享 domain core，而不是拥有 domain core |

### 后续新增模块的自然落点

- `risk/`
  - 最自然的最终落点：`services/signal-service/src/risk/`
  - 当前最好的抽取来源：`src/backtest/models.py:41-50` 的 `RiskConfig`，以及 `src/backtest/execution_engine.py:194-220`、`313-579` 一带的 funding、liquidation、杠杆、容量约束、持仓资金口径
  - 不建议放在：`src/engines/`、`src/storage/history.py`、`src/backtest/__main__.py`
- `paper_trading/`
  - 最自然的最终落点：`services/signal-service/src/paper_trading/`
  - 依赖关系：上游消费 `src/events/types.py:10-87` 的 signal intent，下游复用从 `backtest/models.py` / `execution_engine.py` 抽出的仓位、成交、风险状态机
  - 不建议放在：`src/backtest/runner.py` 或 `src/backtest/execution_engine.py` 原地继续长，因为 paper trading 是 live runtime，不是 artifact pipeline
- `execution_protocol/`
  - 最自然的最终落点：`services/signal-service/src/execution_protocol/`
  - 位置建议：与 `src/events/` 平级，定义 `OrderIntent / OrderAck / Fill / Reject / PositionSnapshot` 等契约；`events/` 继续负责 publish/subscribe，`execution_protocol/` 负责类型与状态转换语义
  - 不建议放在：`SignalEvent.extra`、`pg_engine.py` 内部 dataclass、`storage/history.py` 的松散 JSON extra

## Risks

- 如果后续直接在 `src/engines/pg_engine.py` / `src/engines/sqlite_engine.py` 里增加交易状态，轮询检测周期会被默认为交易事务边界，导致重放、恢复、测试和异常补偿都变得脆弱。
- 如果 live 侧重新实现一套 `risk / execution` 逻辑，而不是从 `backtest/models.py` / `backtest/execution_engine.py` 抽共享语义，回测与实盘会很快出现行为漂移，`walkforward` / `comparison` 的解释力会下降。
- 如果把 `src/storage/history.py` 或 `src/storage/cooldown.py` 继续升格为交易真状态存储，现有的 cleanup、append-only、duck typing 和 SQLite 文件级约束会变成长期负担。
- 如果继续让多种 `SignalEvent` / `PGSignal` / `history normalized payload` 并存而不统一契约，未来任何 execution 相关功能都会先花时间做 shape mapping，而不是实现业务本身。

## Recommendation

- 直接结论：`signal-service` 现在更适合作为 `signal intent / rule evaluation` 的主承接层，而不是在当前结构上直接升级成完整交易域主承接层。
- 适合继续长的地方：
  - `src/rules/`：继续承接规则定义、信号分类、稳定 `rule_id`
  - `src/events/`：继续作为事件传输边界
  - `src/storage/cooldown.py`、`src/storage/read_only.py`：继续作为基础设施 / read model
  - `src/backtest/models.py`、`src/backtest/execution_engine.py`：作为未来共享 domain core 的抽取源
- 不应继续长的地方：
  - `src/engines/pg_engine.py`
  - `src/engines/sqlite_engine.py`
  - `src/storage/history.py`
  - `src/storage/subscription.py`
  - `src/backtest/__main__.py`、`src/backtest/runner.py`、`src/backtest/reporter.py`、`src/backtest/comparison.py`
- 建议的下一步顺序：
  1. 先冻结 `engines/*` 为 adapter，不再往里面加新的有状态交易逻辑
  2. 从 `backtest/models.py` + `backtest/execution_engine.py` 抽出共享 live domain primitives
  3. 以平级新包的方式引入 `src/risk/`、`src/paper_trading/`、`src/execution_protocol/`
  4. 让 `backtest/` 反向消费这套共享 core，而不是继续独占它

## 执行记录

- 2026-03-25：核查了 `src/__main__.py`、`src/storage/{read_only.py,cooldown.py,history.py,subscription.py}`、`src/engines/{pg_engine.py,sqlite_engine.py}`、`src/backtest/` 关键模块。
- 2026-03-25：确认当前最像“域内核”的交易语义位于 `backtest/models.py` + `backtest/execution_engine.py`，而当前最大的结构阻碍位于 `pg_engine.py` 的多职责膨胀。
- 2026-03-25：当前 workspace 未包含 Linear 描述中指向的本地 issue 文件，已按该 authoritative 描述在指定路径补建并回填 review 结论。
