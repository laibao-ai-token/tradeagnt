# tradeagnt Agent Skill

tradeagnt **V2 以 Agent 为主用户**：Harness = manifest + 只读研究 + thesis 闸门 + 纸面 + 审计。人类可用 `tradecat tui` 监控。

- 产品需求：[docs/20260527-V2/PRD.md](../../docs/20260527-V2/PRD.md)
- 机器契约：`agents/manifest.json`（v2 起含写路径）
- 验收：[docs/20260527-V2/ACCEPTANCE.md](../../docs/20260527-V2/ACCEPTANCE.md)

## V2 推荐流程（目标态）

1. 读 `agents/manifest.json`（风险类 + 命令表）
2. `python scripts/tradecat_get_context_pack.py --symbol BTC_USDT`（或 `NVDA`）
3. 按需 `tradecat_get_signals` / `quotes` / `news`
4. 生成 `agent_trade_thesis.v1` JSON（见 `docs/20260527-V2/examples/agent_trade_thesis.example.json`）
5. `tradecat agent submit-thesis --input thesis.json`（M2 实现后）
6. `tradecat agent paper-report --json`

**v1.0 封板期**：步骤 5～6 可能尚未实现；以 manifest 与 PRD 里程碑为准。

## 环境

```bash
source .venv/bin/activate
export TRADECAT_PIPELINE_PROFILE=tui_dual
```

封板范围：`docs/FREEZE_SCOPE.md`。
