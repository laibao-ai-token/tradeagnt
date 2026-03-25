# 主仓切换决策：TradeAgent 主线转向 OpenAlice

> 最后更新: 2026-03-25
> 适用范围: `tradeagent` 后续主线仓选择、旧仓封板口径、参考仓定位
> 当前状态: decision
> 总体结论: 后续 `tradeagent` 主线以 `repository/OpenAlice` 推进；`tradecat-origin` 进入封板维护态；`repository/openclaw.backup-20260324T161300Z` 仅作为运行时/交互能力参考仓

---

## 决策结论

从 `2026-03-25` 起，仓角色正式按下列方式定义：

1. `repository/OpenAlice`
   - 作为 `tradeagent` 的新主线仓
   - 后续架构演进、主功能承接、交易域实现都以此为基座推进

2. `tradecat-origin`
   - 作为封板旧仓
   - 仅承接：
     - 关键 bugfix
     - 只读核验
     - 能力迁移对照
     - 数据/脚本/领域知识提取
   - 不再作为未来主架构继续扩展

3. `repository/openclaw.backup-20260324T161300Z`
   - 作为参考仓
   - 仅用于吸收：
     - gateway / daemon
     - channel / connector
     - node / canvas
     - multi-agent routing
     - onboarding / runtime 运维思路
   - 不作为 `tradeagent` 主仓

## 为什么做这个决策

### 1. `tradecat-origin` 已不适合作为继续演进的主架构仓

当前仓库 review 已经明确：

- `signal-service` 还不具备自然承接完整交易域的结构边界，见 `009`
- `trading-service` 存在超大脚本和分层漏口，见 `010`
- `scripts/`、`tui-service`、`repository/*` 的边界虽然已明确，但要继续把现有实现收口成长期稳定主架构，成本偏高

结论不是“TradeCat 完全不能用”，而是“继续在这套骨架上承载未来主线，维护成本会越来越高”。

### 2. `OpenAlice` 更接近 `tradeagent` 的目标形态

`repository/OpenAlice` 当前已经具备以下更贴近主线目标的结构特征：

- trading-native：内建 `UTA`、`guard pipeline`、`trading-as-git`
- file-driven：以文件、JSON、JSONL 作为持久化和协作基础
- 有明确的交易域、事件、研究、news、UI 一体化结构
- 自带 AI provider、tool center、event log、connector/web UI 等可扩展中枢

这意味着它不是“需要被改造成交易系统”的通用壳，而是“已经是交易代理框架”的更合适底座。

### 3. `openclaw.backup` 的优势在运行时与网关，不在交易主域

`repository/openclaw.backup-20260324T161300Z` 当前更强的是：

- 多通道网关
- daemon / onboard / doctor / runtime 运维
- node / canvas / voice / channel routing
- assistant 平台级能力

但它本质仍是通用 personal assistant / gateway 平台，而不是交易域主内核。  
因此它适合作为“能力供体”，不适合作为 `tradeagent` 主仓。

## 明确不采用的方案

### 方案 A：继续以 `tradecat-origin` 为主仓硬收口

不采用原因：

- 需要在现有 Python 微服务结构上继续做较大幅度架构整形
- `signal-service` 与 `trading-service` 两处核心收口成本都不低
- 会把未来主线时间继续消耗在“修仓型维护”而不是“新主线推进”

### 方案 B：`OpenAlice` 与 `openclaw` 双主仓并行

不采用原因：

- 会形成双架构源头，边界重新失焦
- 交易主域、运行时、UI、渠道的归属会再次混乱
- 迁移讨论会从“往哪迁”变成“两个都改一点”

### 方案 C：以 `openclaw.backup` 为主仓推进交易能力

不采用原因：

- 通用 assistant 平台不是交易主域框架
- 容易把大量时间花在平台改造，而不是交易能力承接
- 当前目录本身是 backup 快照，不适合作为正式主线口径

## 三个仓后续角色

### `repository/OpenAlice`

定义：

- 主产品仓
- 主架构仓
- 主功能推进仓

适合承接：

- 交易域主线
- risk / paper / execution
- research / market context
- 交互界面与 agent orchestration

### `tradecat-origin`

定义：

- 冻结旧仓
- 能力来源仓
- 数据/脚本/规则/回测经验来源仓

适合承接：

- 稳定只读桥接命令的迁移参考
- 现有交易数据、信号、回测口径对照
- 规则、指标、数据采集经验的拆解迁移

不适合承接：

- 新主线架构扩展
- 新交易运行时
- 新 UI / 新 agent 主框架

### `repository/openclaw.backup-20260324T161300Z`

定义：

- 运行时参考仓
- 网关/交互能力参考仓

适合承接：

- gateway 设计参考
- channel / connector 能力参考
- daemon / onboarding / doctor / runtime 运维参考
- 节点、canvas、multi-agent 路由参考

不适合承接：

- 交易主域
- 主数据模型
- 主交易状态机

## 立即生效的推进规则

1. 后续如果说“主仓”，默认指 `repository/OpenAlice`
2. 后续如果说“旧仓”或“存量仓”，默认指 `tradecat-origin`
3. 后续如果说“运行时参考仓”，默认指 `repository/openclaw.backup-20260324T161300Z`
4. 不再继续把 `tradecat-origin` 的当前目录结构作为未来架构收口目标
5. 不再把 `openclaw.backup` 当成主线候选，只当能力参考

## 对 `tradecat-origin` 的封板口径

封板不等于废弃。

`tradecat-origin` 封板后的允许动作：

- 修复阻断当前使用的关键问题
- 补齐迁移所需文档
- 导出规则、指标、桥接命令、runbook、数据口径
- 作为对照仓验证迁移后行为

`tradecat-origin` 封板后的禁止方向：

- 继续做新的主线架构设计
- 继续扩充新的交易域模块
- 把临时实现又堆回 `signal-service` / `tui-service` / `scripts/`

## 迁移原则

迁移的对象应是：

- 领域能力
- 数据口径
- 风险控制口径
- 只读桥接契约
- runbook 与运维经验

迁移的对象不应是：

- 把 `tradecat-origin` 的目录结构原样搬到 `OpenAlice`
- 把现有 Python 微服务边界强行复制到新主仓
- 把 `openclaw` 的平台结构硬贴到交易主域里

## 下一步顺序

1. 先确认主仓切换决策
2. 再输出 `TradeCat -> OpenAlice` 的能力迁移清单
3. 再定义第一批真正要迁的能力：
   - 规则/信号
   - 指标/market data
   - risk / paper / execution 所需输入
4. 最后才进入代码级迁移与新主仓实现

## 一句话口径

后续 `tradeagent` 主线以 `OpenAlice` 为主仓推进，`TradeCat` 封板为存量能力仓，`openclaw.backup` 仅作为运行时与交互能力参考仓。
