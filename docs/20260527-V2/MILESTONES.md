# tradeagnt V2 工程里程碑（Checklist）

> 由 [PRD.md](./PRD.md) 拆解；完成项打 `[x]`。  
> **不要**在未更新 PRD 的情况下增加 P0 项。

---

## M0 — PRD 冻结

- [x] 撰写 `docs/20260527-V2/PRD.md`
- [x] 撰写 `docs/20260527-V2/ACCEPTANCE.md`
- [x] 自 `tradeagnt` 创建分支 `v2/agent-harness`
- [ ] 产品确认开放问题 Q1～Q5（见 PRD §10）
- [ ] 冻结 P0 范围（签字 = 在 PRD 改状态为 **Approved**）

---

## M1 — 契约层

- [ ] `contracts/agent_trade_thesis.schema.json`（+ 可选 context）
- [ ] `src/tradecat/agent/envelope.py`（统一 `{ok,data,error,warnings}`）
- [ ] `skills/tradeagnt/agents/manifest.json` → v2
- [ ] `docs/20260527-V2/examples/agent_trade_thesis.example.json`
- [ ] `tradecat agent thesis-validate`（或脚本等价）
- [ ] 测试：`tests/test_agent_thesis_schema.py`
- [ ] AC-01, AC-02, AC-03（部分）

---

## M2 — Harness 写路径

- [ ] `src/tradecat/agent/audit.py` → `data/agent_audit.jsonl`
- [ ] `src/tradecat/agent/thesis.py`（解析 + 映射 paper）
- [ ] `src/tradecat/cli/agent.py` → `submit-thesis`
- [ ] fail-closed 错误码表（与官方语义对齐）
- [ ] `TRADEAGNT_AGENT_MODE` / daemon 互斥
- [ ] 测试：`tests/test_agent_submit_thesis.py`
- [ ] AC-10～AC-14, AC-30

---

## M3 — 报告、文档、封板

- [ ] `tradecat agent paper-report --json`
- [ ] `scripts/v2_verify.sh` + CI optional job
- [ ] 更新 `skills/tradeagnt/SKILL.md`、`AGENTS.md`、`README.md`
- [ ] `docs/FREEZE_SCOPE.md` 或新建 `V2_FREEZE_SCOPE.md`
- [ ] AC-20, AC-21, AC-40, AC-41
- [ ] tag `v2.0.0`

---

## M4+（P1，非 V2.0）

- [ ] `context-audit`（FR-15）
- [ ] freshness gate（FR-32）
- [ ] TUI audit 面板（FR-42）
- [ ] 公开表 signal_flow 适配（FR-33）
