import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.Optional(Type.String({ description: "Optional symbol filter, e.g. BTCUSDT or NVDA" })),
	audit_limit: Type.Optional(Type.Number({ description: "Recent audit rows to inspect (default 20)" })),
	signal_limit: Type.Optional(Type.Number({ description: "Recent signal rows to include (default 10)" })),
});

export function registerFeedbackPackTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_feedback_pack",
		label: "Trade Feedback Pack",
		description:
			"Build a read-only E4 feedback pack from paper audit, paper report, and recent signals. It does not submit paper orders or write strategy files.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const auditLimit = Math.max(1, Math.floor(params.audit_limit ?? 20));
			const signalLimit = Math.max(0, Math.floor(params.signal_limit ?? 10));
			const args = ["--audit-limit", String(auditLimit), "--signal-limit", String(signalLimit)];
			if (params.symbol) {
				args.push("--symbol", params.symbol);
			}

			const result = await runTradeScript("tradecat_agent_feedback_pack.py", args, {
				timeoutMs: 30_000,
			});
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol, auditLimit, signalLimit },
			};
		},
	});
}
