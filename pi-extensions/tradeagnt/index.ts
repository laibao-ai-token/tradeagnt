/**
 * tradeagnt E2 — Pi Extension: quotes, indicators, news, signals (read-only).
 *
 * Load: pi -e /path/to/tradeagnt/pi-extensions/tradeagnt/index.ts
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { resolveTradeagntRoot } from "./run-python.js";
import { registerBacktestTool } from "./tools/backtest.js";
import { registerIndicatorsTool } from "./tools/indicators.js";
import { registerNewsTool } from "./tools/news.js";
import { registerPaperReportTool } from "./tools/paper-report.js";
import { registerQuotesTool } from "./tools/quotes.js";
import { registerSignalsTool } from "./tools/signals.js";
import { registerSubmitTool } from "./tools/submit.js";

export default function (pi: ExtensionAPI) {
	const root = resolveTradeagntRoot();
	process.env.TRADEAGNT_ROOT = root;

	registerQuotesTool(pi);
	registerIndicatorsTool(pi);
	registerNewsTool(pi);
	registerSignalsTool(pi);
	registerSubmitTool(pi);
	registerPaperReportTool(pi);
	registerBacktestTool(pi);

	pi.on("session_start", async (_event, ctx) => {
		ctx.ui.notify(`tradeagnt tools loaded (root=${root})`, "info");
	});

	pi.registerCommand("trade", {
		description: "List tradeagnt tools (E2 read-only + E3 paper + E3 backtest)",
		handler: async (_args, ctx) => {
			ctx.ui.notify(
				"Tools: trade_get_quotes, trade_get_indicators, trade_get_news, trade_get_signals (E2 read-only); trade_submit_thesis, trade_paper_report (E3 paper); trade_run_backtest (E3 backtest) — see E2/E3 docs",
				"info",
			);
		},
	});
}
