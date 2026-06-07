import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.String({ description: "Symbol filter, e.g. BTC_USDT" }),
	timeframe: Type.Optional(Type.String({ description: "Timeframe, e.g. 5m (default 5m)" })),
	limit: Type.Optional(Type.Number({ description: "Max rows (default 10)" })),
});

export function registerSignalsTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_get_signals",
		label: "Trade Signals",
		description:
			"Read recent strategy signals from signal_history.db (direction, strength, rule message). Output of SignalEngine; not raw indicators.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const timeframe = params.timeframe || "5m";
			const limit = params.limit ?? 10;
			const args = [
				"--symbol",
				params.symbol,
				"--timeframe",
				timeframe,
				"--limit",
				String(Math.min(Math.max(1, Math.floor(limit)), 500)),
			];
			const result = await runTradeScript("tradecat_get_signals.py", args);
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol, timeframe, limit },
			};
		},
	});
}
