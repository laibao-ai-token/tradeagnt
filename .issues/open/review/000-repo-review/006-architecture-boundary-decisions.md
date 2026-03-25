# 架构边界定稿

> 最后更新: 2026-03-24
> 适用范围: `#007` 实现前的主仓架构边界冻结
> 核实状态: 已结合 `001-005` 文档、当前脚本入口、`signal-service`、`tui-service` 现状核实
> 总体结论: 当前最大的架构问题不是服务内部失控，而是桥接层未独立成层、主仓边界未被正式编码

---

## 结论先行

从当前主仓看，真正需要先定死的不是“某个函数怎么写”，而是以下 4 条边界：

1. `scripts/` 和 `scripts/lib/` 只负责只读桥接入口与桥接组装
2. `services/signal-service/` 负责所有有状态的交易领域能力
3. `services-preview/tui-service/` 只负责展示与只读适配，不承接交易域状态
4. `repository/*` 只视为外挂仓 / 参考仓，不属于 TradeCat 主线架构边界；此前绑定的外部 runtime 路线已从主仓主流程移除

如果这 4 条不先冻结，后续 `#007` 会持续在 bridge、UI、外部编排层、服务内部之间来回漂移。

## 当前主要架构问题

### 1. Bridge / Domain Layer 还没有真正独立

当前现状是：

- `tradecat_get_quotes.py` 直接依赖 `tui-service` 的 `quote.py`
- `tradecat_get_signals.py` 直接挂 `signal-service` 模块路径
- 新闻查询在 `scripts/lib/tradecat_news.py` 与 `tui-service/src/news_db.py` 中各有一套读实现

这说明：

- 桥接层已经存在“入口”
- 但还没有存在“唯一实现层”

问题不在于有没有桥，而在于桥接实现散落在多个归属不同的模块里。

### 2. `#007` 目标边界已经写出来，但代码归属还没冻结

`#007` 已经明确：

- `TradeCat` 主仓继续负责数据、指标、信号、回测、TUI
- 中间要有 `Bridge / Domain Layer`
- 外部编排层只消费稳定命令和领域对象

但当前代码还停留在“文档上知道该怎么分，代码里还没把归属写死”的状态。

### 3. TUI 里仍有 Agent Shell 占位壳，容易误导后续实现

当前 `tui-service` 中仍保留了本地 placeholder Agent Shell。  
这本身对演示没问题，但对架构推进有一个风险：

- 后续实现很容易顺手把 bridge 或 runtime 逻辑继续塞回 TUI

所以这里必须做边界声明，而不是只依赖口头约定。

### 4. `repository/*` 容易干扰主仓讨论

`repository/` 下存在多个外挂仓与参考仓。  
这些目录对联调或调研有价值，但不应反向定义 TradeCat 主仓的模块边界。

## 冻结后的边界

## 1. `scripts/` 和 `scripts/lib/`

### 负责什么

- 只读桥接命令入口
- 领域对象组装
- `context pack` 聚合
- 审计查询 / 回放 CLI
- 供外部编排层消费的稳定本地命令

### 不负责什么

- 交易状态机
- 风控规则核心
- 持仓、订单、执行协议持久化
- 任何长期有状态的交易工作流

### 结论

`scripts/` 是桥接层入口，不是交易领域核心。

## 2. `services/signal-service/`

### 负责什么

- 规则信号
- 冷却状态
- 回测与预检
- 未来的 `risk/`
- 未来的 `paper_trading/`
- 未来的 `execution_protocol/`

### 不负责什么

- TUI 展示
- 外部编排 runtime
- 外部 skill / workbench 分发

### 结论

所有“有状态的交易领域能力”统一收口到 `signal-service`。

## 3. `services-preview/tui-service/`

### 负责什么

- 终端展示
- 只读数据适配
- Quote / News / DB 读取消费层
- 事件 DTO 与展示状态

### 不负责什么

- 下单候选生成
- 统一风险判定
- 执行协议状态机
- Agent runtime 主逻辑

### 结论

`tui-service` 是消费层，不是交易领域层。

## 4. `repository/*`

### 定位

- 参考实现
- 联调副本
- 外挂工具仓

### 结论

默认不纳入主仓架构边界讨论，也不纳入主仓默认 code review 范围。  
当前主仓内此前绑定的外部 runtime 路线已退出主流程，后续不再作为 `#007` 的依赖前提。

## 立即生效的实现约束

从现在开始，后续 `#007` 实现应遵守以下规则：

1. 新的只读领域对象命令，优先新增在 `scripts/`
2. 新的桥接组装 helper，优先放 `scripts/lib/`
3. 新的风险、paper、execution 逻辑，优先放 `services/signal-service/src/`
4. `tui-service` 只能消费这些能力，不能成为这些能力的主实现
5. 外部编排层只能调用桥接层，不能复制或拥有主仓领域状态

## 当前允许的“过渡态”

以下过渡态是当前可接受的：

- `scripts` 暂时直接调用服务内部只读模块
- `tui-service` 暂时保留 Agent Shell placeholder
- 桥接 CLI 仍各自维护顶层 JSON 包络

但这些都只是过渡态，不应被当成最终架构。

## 当前不允许继续扩大的方向

以下方向从现在开始应视为“架构违例”：

1. 把新的交易工作流继续塞进 `tui-service`
2. 把新的交易状态机实现放进 `repository/*` 外挂仓
3. 在 `scripts/` 中长期持有订单、持仓、执行状态
4. 继续复制新闻/信号/桥接读逻辑到更多模块

## 推荐收敛顺序

### Step 1

先把 bridge contract 收口：

- 统一只读领域对象
- 统一顶层 JSON 契约
- 减少桥接层中的重复实现

### Step 2

再把有状态交易域长进 `signal-service`：

- `risk/`
- `paper_trading/`
- `execution_protocol/`

### Step 3

最后再收 UI 侧：

- `tui-service` 只保留展示
- 外部编排层只保留消费与交互

## 这份文档的作用

这份文档不是新方案，而是把当前已经得到的架构结论正式冻结下来。  
后续任何实现、review、拆 issue，都应优先服从这里的边界，而不是临时拍脑袋决定落位。
