import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

function payloadData(payload: Record<string, unknown> | null): Record<string, unknown> {
	const data = payload?.data;
	return data && typeof data === "object" && !Array.isArray(data) ? data as Record<string, unknown> : {};
}

function field(data: Record<string, unknown>, name: string): unknown {
	return data[name] ?? null;
}

function summaryField(data: Record<string, unknown>, name: string): unknown {
	const summary = field(data, "rehearsal_chain_summary");
	return summary && typeof summary === "object" && !Array.isArray(summary)
		? (summary as Record<string, unknown>)[name] ?? null
		: null;
}

const Params = Type.Object({
	strategy: Type.String({
		description: 'Baseline strategy to rehearse, e.g. "current/fast_1m.yaml"',
	}),
	symbol: Type.String({ description: "Symbol to optimize for, e.g. BTC_USDT" }),
	watchlist: Type.Optional(Type.String({ description: "Optional comma-separated watchlist" })),
	market: Type.Optional(Type.String({ description: "Optional market hint" })),
	days: Type.Optional(Type.Number({ description: "Lookback days for loop/evolve (default 1)" })),
	rounds: Type.Optional(Type.Number({ description: "Suggest loop rounds before rehearsal, clamped to 1-5" })),
	cycles: Type.Optional(Type.Number({ description: "Feedback rehearsal cycles, clamped to 1-5. Default 1." })),
	candidate_count: Type.Optional(Type.Number({ description: "Candidate count, clamped to 2-5" })),
	verify_mode: Type.Optional(
		Type.Union([Type.Literal("suggest"), Type.Literal("dry_run")], {
			description: "File adapter verification mode. Default suggest; paper is not allowed.",
		}),
	),
	run_id: Type.Optional(Type.String({ description: "Optional fixed rehearsal id" })),
	previous_rehearsal_feedback: Type.Optional(
		Type.String({ description: "Optional rehearsal_feedback.json path or JSON object used as the first cycle seed" }),
	),
	previous_rehearsal_chain_summary: Type.Optional(
		Type.String({
			description: "Optional rehearsal_chain_summary.json path or JSON object used as the first cycle seed",
		}),
	),
	include_news: Type.Optional(
		Type.Boolean({ description: "Optionally include read-only news context; default false" }),
	),
	news_limit: Type.Optional(Type.Number({ description: "Max news articles when include_news is true" })),
	news_since_minutes: Type.Optional(Type.Number({ description: "News lookback minutes when include_news is true" })),
});

export function registerStrategyRehearsalTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_strategy_rehearsal",
		label: "Trade Strategy Rehearsal",
		description:
			"Run a safe E5 rehearsal: suggest loop -> write deterministic stub Agent JSON to agent_generator_output.json -> verify through the file adapter in suggest/dry_run. It does not call an LLM, run paper/live, or change current.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const days = Math.max(1, Math.floor(params.days ?? 1));
			const rounds = Math.max(1, Math.min(5, Math.floor(params.rounds ?? 2)));
			const cycles = Math.max(1, Math.min(5, Math.floor(params.cycles ?? 1)));
			const candidateCount = Math.max(2, Math.min(5, Math.floor(params.candidate_count ?? 2)));
			const args = [
				"--strategy",
				params.strategy,
				"--symbol",
				params.symbol,
				"--days",
				String(days),
				"--rounds",
				String(rounds),
				"--cycles",
				String(cycles),
				"--candidate-count",
				String(candidateCount),
			];
			if (params.watchlist) {
				args.push("--watchlist", params.watchlist);
			}
			if (params.market) {
				args.push("--market", params.market);
			}
			if (params.verify_mode) {
				args.push("--verify-mode", params.verify_mode);
			}
			if (params.run_id) {
				args.push("--run-id", params.run_id);
			}
			if (params.previous_rehearsal_feedback) {
				args.push("--previous-rehearsal-feedback", params.previous_rehearsal_feedback);
			}
			if (params.previous_rehearsal_chain_summary) {
				args.push("--previous-rehearsal-chain-summary", params.previous_rehearsal_chain_summary);
			}
			if (params.include_news) {
				args.push("--include-news");
				args.push("--news-limit", String(Math.max(1, Math.min(20, Math.floor(params.news_limit ?? 5)))));
				args.push("--news-since-minutes", String(Math.max(1, Math.floor(params.news_since_minutes ?? 240))));
			}

			const result = await runTradeScript("tradecat_strategy_rehearsal.py", args, {
				timeoutMs: Math.max(600_000, cycles * rounds * 330_000),
			});
			const data = payloadData(result.payload);
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: {
					strategy: params.strategy,
					symbol: params.symbol,
					days,
					rounds,
					cycles,
					candidateCount,
					verifyMode: params.verify_mode ?? "suggest",
					runId: params.run_id,
					hasPreviousRehearsalFeedback: Boolean(params.previous_rehearsal_feedback),
					hasPreviousRehearsalChainSummary: Boolean(params.previous_rehearsal_chain_summary),
					includeNews: Boolean(params.include_news),
					agentGeneratorOutput: field(data, "agent_generator_output"),
					loopAgentGeneratorTask: field(data, "loop_agent_generator_task"),
					rehearsalFeedback: field(data, "rehearsal_feedback"),
					rehearsalChainSummary: field(data, "rehearsal_chain_summary"),
					nextAgentGeneratorRequest: summaryField(data, "next_agent_generator_request"),
					nextRehearsalRequest: summaryField(data, "next_rehearsal_request"),
					nextLoopRequest: summaryField(data, "next_loop_request"),
					cyclesCompleted: field(data, "cycles_completed"),
					cycleFeedbackChain: field(data, "cycle_feedback_chain"),
					loopRunId: field(data, "loop_run_id"),
					verifyRunId: field(data, "verify_run_id"),
					currentChanged: field(data, "current_changed"),
					safety: field(data, "safety"),
				},
			};
		},
	});
}
