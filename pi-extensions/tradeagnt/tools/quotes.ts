import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.String({ description: "Symbol, e.g. BTC_USDT or NVDA" }),
	market: Type.Optional(Type.String({ description: "Optional market override, e.g. crypto_spot, us_stock" })),
});

export function registerQuotesTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_get_quotes",
		label: "Trade Quotes",
		description:
			"Read latest quote for a symbol (price, change, volume). Same source as TUI market page (P1). Returns JSON with ok/data/error.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const args = [params.symbol];
			if (params.market) {
				args.push("--market", params.market);
			}
			const result = await runTradeScript("tradecat_get_quotes.py", args, { timeoutMs: 60_000 });
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol, exitCode: result.exitCode },
			};
		},
	});
}
