import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	strategy: Type.String({ description: "Strategy YAML path, e.g. current/fast_1m.yaml" }),
	symbol: Type.String({ description: "Symbol to backtest, e.g. BTC_USDT" }),
	market: Type.Optional(Type.String({ description: "Optional market override: crypto_spot, us_stock, cn_stock" })),
	days: Type.Optional(Type.Number({ description: "Lookback days (default 7)" })),
	initial_equity: Type.Optional(Type.Number({ description: "Initial equity USDT (default 1000)" })),
});

export function registerBacktestTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_run_backtest",
		label: "Trade Run Backtest",
		description:
			"Run a strategy backtest on a symbol via the existing tradecat backtest CLI; returns a structured JSON summary (Sharpe, drawdown, win rate, trade count). Use to validate a strategy before submit-thesis. Local; no network; may take 30s-2min.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const days = Math.max(1, Math.floor(params.days ?? 7));
			const args = [
				"--strategy",
				params.strategy,
				"--symbol",
				params.symbol,
				"--days",
				String(days),
			];
			if (params.market) {
				args.push("--market", params.market);
			}
			if (params.initial_equity != null) {
				args.push("--initial-equity", String(params.initial_equity));
			}
			const result = await runTradeScript("bridge_backtest.py", args, { timeoutMs: 120_000 });
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { strategy: params.strategy, symbol: params.symbol, days, exitCode: result.exitCode },
			};
		},
	});
}
