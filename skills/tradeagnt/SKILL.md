# tradeagnt Agent Skill

tradeagnt 为 **Agent-first 数据与纸面研究** 提供只读 JSON 工具；人类可选使用 `tradecat tui`。

机器主契约：`agents/manifest.json`。

## 推荐流程

1. 读 `agents/manifest.json` 中 `preferred_readonly_entrypoints`
2. `python scripts/tradecat_get_context_pack.py --symbol BTC_USDT`（或美股 `NVDA`）
3. 按需调用 `tradecat_get_signals` / `tradecat_get_quotes` / `tradecat_get_news`
4. 需要回测摘要时用 `tradecat_get_backtest_summary.py`
5. **v1.0**：勿假设可写 thesis；写入闭环见 `docs/V1_AGENT_HARNESS.md` v1.1

## 环境

```bash
source .venv/bin/activate
export TRADECAT_PIPELINE_PROFILE=tui_dual
```

封板范围：`docs/FREEZE_SCOPE.md`。
