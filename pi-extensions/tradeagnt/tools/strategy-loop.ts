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

const Params = Type.Object({
	strategy: Type.String({
		description: 'Baseline strategy to evolve, e.g. "current/fast_1m.yaml"',
	}),
	symbol: Type.String({ description: "Symbol to optimize for, e.g. BTC_USDT" }),
	watchlist: Type.Optional(Type.String({ description: "Optional comma-separated watchlist" })),
	market: Type.Optional(Type.String({ description: "Optional market hint" })),
	days: Type.Optional(Type.Number({ description: "Lookback days per round (default 7)" })),
	rounds: Type.Optional(Type.Number({ description: "Bounded loop rounds, clamped to 1-10 (default 3)" })),
	candidate_count: Type.Optional(
		Type.Number({ description: "Number of candidates per round, clamped to 2-3" }),
	),
	mode: Type.Optional(
		Type.Union([Type.Literal("suggest"), Type.Literal("dry_run"), Type.Literal("paper")], {
			description:
				"Loop mode. Default dry_run; paper may activate current only when each round's promotion gates pass.",
		}),
	),
	run_id: Type.Optional(Type.String({ description: "Optional fixed loop id" })),
	previous_rejected_reasons: Type.Optional(
		Type.String({ description: "Optional seed rejected reasons, comma/semicolon separated" }),
	),
	previous_repair_guidance: Type.Optional(
		Type.String({ description: "Optional seed repair guidance, comma/semicolon separated" }),
	),
	previous_rehearsal_feedback: Type.Optional(
		Type.String({ description: "Optional rehearsal_feedback.json path or JSON object used as read-only next-loop seed" }),
	),
	previous_rehearsal_chain_summary: Type.Optional(
		Type.String({
			description: "Optional rehearsal_chain_summary.json path or JSON object; resolves next_loop_feedback as seed",
		}),
	),
	include_news: Type.Optional(
		Type.Boolean({ description: "Optionally include read-only news context in each round; default false" }),
	),
	news_limit: Type.Optional(Type.Number({ description: "Max news articles per round when include_news is true" })),
	news_since_minutes: Type.Optional(Type.Number({ description: "News lookback minutes when include_news is true" })),
});

export function registerStrategyLoopTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_strategy_loop",
		label: "Trade Strategy Loop",
		description:
			"Run a bounded multi-round E4/E5 strategy loop. Each round delegates to trade_strategy_evolve, carries clean rejection/repair/risk feedback, and returns loop handoff, Agent continuation, Agent generator task, context health, next action, and submission summaries without changing current in suggest/dry_run.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const days = Math.max(1, Math.floor(params.days ?? 7));
			const rounds = Math.max(1, Math.min(10, Math.floor(params.rounds ?? 3)));
			const candidateCount = Math.max(2, Math.min(3, Math.floor(params.candidate_count ?? 2)));
			const args = [
				"--strategy",
				params.strategy,
				"--symbol",
				params.symbol,
				"--days",
				String(days),
				"--rounds",
				String(rounds),
				"--candidate-count",
				String(candidateCount),
			];
			if (params.watchlist) {
				args.push("--watchlist", params.watchlist);
			}
			if (params.market) {
				args.push("--market", params.market);
			}
			if (params.mode) {
				args.push("--mode", params.mode);
			}
			if (params.run_id) {
				args.push("--run-id", params.run_id);
			}
			if (params.previous_rejected_reasons) {
				args.push("--previous-rejected-reasons", params.previous_rejected_reasons);
			}
			if (params.previous_repair_guidance) {
				args.push("--previous-repair-guidance", params.previous_repair_guidance);
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

			const result = await runTradeScript("tradecat_strategy_loop.py", args, {
				timeoutMs: Math.max(300_000, rounds * 300_000),
			});
			const data = payloadData(result.payload);
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: {
					strategy: params.strategy,
					symbol: params.symbol,
					days,
					rounds,
					candidateCount,
					mode: params.mode ?? "dry_run",
					runId: params.run_id,
					hasPreviousRepairGuidance: Boolean(params.previous_repair_guidance),
					hasPreviousRehearsalFeedback: Boolean(params.previous_rehearsal_feedback),
					hasPreviousRehearsalChainSummary: Boolean(params.previous_rehearsal_chain_summary),
					includeNews: Boolean(params.include_news),
					previousRehearsalFeedbackInputs: field(data, "previous_rehearsal_feedback_inputs"),
					loopArtifacts: {
						agentHandoffs: field(data, "agent_handoffs"),
						agentGeneratorTask: field(data, "agent_generator_task"),
						finalAgentHandoff: field(data, "final_agent_handoff"),
					},
					finalAgentNextAction: field(data, "final_agent_next_action"),
					finalAgentSubmission: field(data, "final_agent_submission"),
					loopAgentContinuation: field(data, "loop_agent_continuation"),
					loopAgentGeneratorTask: field(data, "loop_agent_generator_task"),
					loopContextHealthSummary: field(data, "loop_context_health_summary"),
					loopRiskSummary: field(data, "loop_risk_summary"),
				},
			};
		},
	});
}
