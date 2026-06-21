import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	strategies: Type.String({
		description: 'Comma-separated strategy names to compare, e.g. "fast_1m.yaml,ema_cross.yaml"',
	}),
	symbol: Type.String({ description: "Symbol to backtest, e.g. BTC_USDT" }),
	days: Type.Optional(Type.Number({ description: "Lookback days (default 7)" })),
	market: Type.Optional(Type.String({ description: "Optional market override" })),
	timeframe: Type.Optional(Type.String({ description: "Optional timeframe override" })),
	provider: Type.Optional(Type.String({ description: "Optional provider override" })),
	min_strength: Type.Optional(Type.Number({ description: "Minimum signal strength (default 50)" })),
});

export function registerStrategyCompareTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_strategy_compare",
		label: "Trade Strategy Compare",
		description:
			"Compare baseline plus candidate strategies using structured backtests. Ranks by return/trades/signals and returns winner plus rejected reasons; does not activate strategies.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const days = Math.max(1, Math.floor(params.days ?? 7));
			const minStrength = Math.max(0, Math.floor(params.min_strength ?? 50));
			const args = [
				"--strategies",
				params.strategies,
				"--symbol",
				params.symbol,
				"--days",
				String(days),
				"--min-strength",
				String(minStrength),
			];
			if (params.market) {
				args.push("--market", params.market);
			}
			if (params.timeframe) {
				args.push("--timeframe", params.timeframe);
			}
			if (params.provider) {
				args.push("--provider", params.provider);
			}

			const result = await runTradeScript("tradecat_strategy_compare.py", args, {
				timeoutMs: 180_000,
			});
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { strategies: params.strategies, symbol: params.symbol, days, minStrength },
			};
		},
	});
}
