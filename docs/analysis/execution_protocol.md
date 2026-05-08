# Execution Protocol 审计说明

## 目标

统一记录模拟交易执行链路：

`propose -> validate -> stage -> confirm -> execute -> sync`

并在任何失败场景写入可回放事件，保证单笔决策可追溯。

## 数据落盘

- 路径：`artifacts/execution_audit/`
- 格式：按 `trace_id` 拆分的 append-only `*.jsonl`
- 每行事件字段：
  - `event_id`
  - `trace_id`
  - `intent_id`
  - `order_id`
  - `phase`
  - `status`
  - `timestamp`
  - `details`
  - `error`

## 关键行为

1. `ExecutionProtocol.start_execution()` 写入 `propose`
2. `validate()` 根据 guard 结果写入 `IN_PROGRESS` 或 `REJECTED`
3. `stage()/confirm()/execute()/sync()` 依次推进协议
4. `fail(trace_id, phase, reason)` 在任意阶段写入 `FAILED` 并固化原因

## 与 Paper Trading 的联动

- `paper_trading.orchestrator.confirm_and_execute()` 在执行前强制调用 Guard Pipeline
- guard 失败：订单标记 `REJECTED`，协议停在 `validate`
- 中间步骤失败：写入对应 phase 的 `FAILED`
- 成功路径：完整 6 段事件并在 `sync` 完成

## 回放方式

```bash
# 查看 trace 列表
python scripts/tradecat_execution_audit.py list

# 回放单笔
python scripts/tradecat_execution_audit.py replay <trace_id>
```

回放输出重点字段：

- `status`
- `current_phase`
- `events[]`（按时间顺序）
- `details.reason`（失败场景）

## 验证

已覆盖最小验证：

- `services/signal-service/tests/test_execution_protocol.py`
  - happy path：6 段协议完整回放
  - failed path：失败阶段、原因可回放

