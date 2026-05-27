# tradeagnt V2 验收标准（AC）

> 与 [PRD.md](./PRD.md) 一一对应。实现 PR 应注明所满足的 AC 编号。  
> 自动化入口（计划）：`./scripts/v2_verify.sh`（M2 起纳入 CI optional job）。

---

## 契约与 manifest

| AC | 对应 FR | 验收条件 |
|:---|:---|:---|
| AC-01 | FR-01 | `python -m json.tool skills/tradeagnt/agents/manifest.json` 通过；`schema` 为 `tradeagnt.agent_manifest.v2` |
| AC-02 | FR-02 | 示例 thesis 通过 `jsonschema` 校验（`contracts/agent_trade_thesis.schema.json`） |
| AC-03 | FR-03 | `tradecat agent paper-report --json` 输出含 `ok`、`schema`、`schema_version`；失败时含 `error.code` |

## submit-thesis（P0）

| AC | 对应 FR | 验收条件 |
|:---|:---|:---|
| AC-10 | FR-10 | 合法 thesis → `ok=true`，paper DB 有对应持仓或订单记录 |
| AC-11 | FR-12 | 缺 `paper_intent` 尺寸 → `ok=false`，`error.code=agent_sizing_required`，无持仓变化 |
| AC-12 | FR-12 | `direction=WATCH_ONLY` → 不开仓，`ok=true`，audit 记 `watch_only` |
| AC-13 | FR-14 | 每次 submit 追加一行 `data/agent_audit.jsonl`，含 `outcome`/`error_code` |
| AC-14 | FR-11 | LONG thesis 对 BTCUSDT 与 NVDA 各跑通一例（双市场） |

## 只读兼容

| AC | 对应 FR | 验收条件 |
|:---|:---|:---|
| AC-20 | FR-20 | `tradecat_get_context_pack.py --symbol BTC_USDT` 退出码 0，JSON 可解析 |
| AC-21 | FR-06 | v1.0 `freeze_verify.sh` 仍 PASS（无回归） |

## 运行时隔离

| AC | 对应 FR | 验收条件 |
|:---|:---|:---|
| AC-30 | FR-40 | `TRADEAGNT_AGENT_MODE=1` 时 `auto_consumer` 不消费新信号（或文档化互斥 env） |
| AC-31 | FR-41 | 同 symbol 先 daemon 开仓再 submit 冲突 thesis → 行为符合 PRD Q3 默认（warn 或 reject，需实现后锁定） |

## 文档

| AC | 对应 FR | 验收条件 |
|:---|:---|:---|
| AC-40 | FR-50 | `skills/tradeagnt/SKILL.md` 描述 V2 Agent 主路径，无「仅 v1.0 只读」作为最终态 |
| AC-41 | FR-51 | `AGENTS.md` 列出 `tradecat agent *` 与风险类 |

---

## 手工冒烟（发布前）

```bash
# 1) 只读
python scripts/tradecat_get_context_pack.py --symbol BTC_USDT

# 2) 校验示例 thesis（M1+）
tradecat agent thesis-validate --input docs/20260527-V2/examples/agent_trade_thesis.example.json

# 3) 提交（M2+）
tradecat agent submit-thesis --input docs/20260527-V2/examples/agent_trade_thesis.example.json

# 4) 报告
tradecat agent paper-report --json
```

---

## 状态

| 里程碑 | P0 AC 状态 |
|:---|:---|
| M0 PRD | 本文档已建，**待确认 Q1～Q5** |
| M1 契约 | 未开始 |
| M2 写路径 | 未开始 |
| M3 tag | 未开始 |
