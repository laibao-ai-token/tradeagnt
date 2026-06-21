/**
 * tradeagnt E2 — Pi Extension: quotes, indicators, news, signals (read-only).
 *
 * Load: pi -e /path/to/tradeagnt/pi-extensions/tradeagnt/index.ts
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { resolveTradeagntRoot } from "./run-python.js";
import { registerBacktestTool } from "./tools/backtest.js";
import { registerFeedbackPackTool } from "./tools/feedback-pack.js";
import { registerIndicatorsTool } from "./tools/indicators.js";
import { registerNewsTool } from "./tools/news.js";
import { registerPaperReportTool } from "./tools/paper-report.js";
import { registerQuotesTool } from "./tools/quotes.js";
import { registerSignalsTool } from "./tools/signals.js";
import { registerSubmitTool } from "./tools/submit.js";
import { registerStrategyManageTool } from "./tools/strategy-manage.js";
import { registerStrategyCompareTool } from "./tools/strategy-compare.js";
import { registerStrategyEvolveTool } from "./tools/strategy-evolve.js";
import { registerStrategyLoopTool } from "./tools/strategy-loop.js";
import { registerStrategyRehearsalTool } from "./tools/strategy-rehearsal.js";

export default function (pi: ExtensionAPI) {
	const root = resolveTradeagntRoot();
	process.env.TRADEAGNT_ROOT = root;

	// E2 read-only tools
	registerQuotesTool(pi);
	registerIndicatorsTool(pi);
	registerNewsTool(pi);
	registerSignalsTool(pi);
	// E3 paper trading tools
	registerSubmitTool(pi);
	registerPaperReportTool(pi);
	registerBacktestTool(pi);
	// E4 read-only feedback
	registerFeedbackPackTool(pi);
	// E4/E5 strategy optimization tools
	registerStrategyManageTool(pi);
	registerStrategyCompareTool(pi);
	registerStrategyEvolveTool(pi);
	registerStrategyLoopTool(pi);
	registerStrategyRehearsalTool(pi);

	pi.on("session_start", async (_event, ctx) => {
		ctx.ui.notify(`tradeagnt tools loaded (root=${root})`, "info");
	});

	pi.registerCommand("trade", {
		description: "List tradeagnt tools (E2 read-only + E3 paper + E4/E5 strategy)",
		handler: async (_args, ctx) => {
			ctx.ui.notify(
				"E2: trade_get_quotes, trade_get_indicators, trade_get_news, trade_get_signals | " +
				"E3: trade_submit_thesis, trade_paper_report, trade_run_backtest | " +
				"E4: trade_feedback_pack | E4/E5 strategy tools: trade_strategy_manage, trade_strategy_compare, trade_strategy_evolve, trade_strategy_loop, trade_strategy_rehearsal (Agent handoff/generator artifacts)",
				"info",
			);
		},
	});
}
