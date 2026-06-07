import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	symbol: Type.String({ description: "Symbol, e.g. BTC_USDT or SH688041" }),
	market: Type.Optional(
		Type.String({ description: "Optional market: cn_stock, us_stock, crypto_spot (auto-inferred if omitted)" }),
	),
	timeframe: Type.Optional(
		Type.String({
			description:
				"Kline timeframe: default 5m. CN/HK off-hours: use 5m (Tencent minute replay). 1d needs Eastmoney; auto-falls back to 5m if unavailable.",
		}),
	),
	indicator: Type.Optional(
		Type.String({ description: "Comma-separated names: rsi,ema,macd,... (default bundle)" }),
	),
});

export function registerIndicatorsTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_get_indicators",
		label: "Trade Indicators",
		description:
			"Technical indicators (RSI, EMA, MACD) from K-lines. CN/HK: Tencent minute (default 5m) or Eastmoney daily (1d, with minute fallback). Crypto/US: exchange providers. Always call this for indicator questions—not quotes alone.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const timeframe = params.timeframe || "5m";
			const args = ["--symbol", params.symbol, "--timeframe", timeframe];
			if (params.market) {
				args.push("--market", params.market);
			}
			if (params.indicator) {
				args.push("--indicator", params.indicator);
			}
			const result = await runTradeScript("tradecat_get_indicators.py", args, { timeoutMs: 60_000 });
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { symbol: params.symbol, timeframe },
			};
		},
	});
}
