import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.Optional(Type.String({ description: "Optional symbol filter, e.g. BTC_USDT or SH688041" })),
	limit: Type.Optional(Type.Number({ description: "Max articles (default 5)" })),
	since_minutes: Type.Optional(Type.Number({ description: "Lookback minutes (default 120)" })),
});

export function registerNewsTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_get_news",
		label: "Trade News",
		description:
			"Recent news (PostgreSQL or RSS fallback if DB down). Optional symbol filter; without symbol returns headline feed.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const limit = params.limit ?? 5;
			const since = params.since_minutes ?? 120;
			const args = [
				"--limit",
				String(Math.min(Math.max(1, Math.floor(limit)), 200)),
				"--since-minutes",
				String(Math.max(1, Math.floor(since))),
			];
			if (params.symbol?.trim()) {
				args.unshift("--symbol", params.symbol.trim());
			}
			const result = await runTradeScript("tradecat_get_news.py", args, { timeoutMs: 90_000 });
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol, limit, since_minutes: since },
			};
		},
	});
}
