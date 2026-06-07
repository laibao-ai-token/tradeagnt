import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.Optional(Type.String({ description: "Filter recent rejects by symbol" })),
	include_rejects: Type.Optional(Type.Number({ description: "Number of recent reject rows", default: 5 })),
});

export function registerPaperReportTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_paper_report",
		label: "Trade Paper Report",
		description: "Paper account NAV, positions, and recent agent thesis rejections (local SQLite).",
		parameters: Params,
		async execute(_toolCallId, params) {
			const args: string[] = [];
			if (params.symbol) {
				args.push("--symbol", params.symbol);
			}
			if (params.include_rejects != null) {
				args.push("--include-rejects", String(params.include_rejects));
			}
			const result = await runTradeScript("tradecat_agent_paper_report.py", args, { timeoutMs: 60_000 });
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol },
			};
		},
	});
}
