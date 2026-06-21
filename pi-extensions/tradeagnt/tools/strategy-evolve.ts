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
	days: Type.Optional(Type.Number({ description: "Lookback days for backtest (default 7)" })),
	candidate_count: Type.Optional(
		Type.Number({ description: "Number of candidates to generate/consume, clamped to 2-3 for deterministic and 2-5 for Agent drafts" }),
	),
	agent_candidates: Type.Optional(
		Type.String({
			description:
				"Optional Agent-authored candidates as JSON string or JSON file path. Each candidate needs hypothesis, changes, and YAML content.",
		}),
	),
	agent_generator_mode: Type.Optional(
		Type.Union([Type.Literal("off"), Type.Literal("file")], {
			description: "Explicit Agent/LLM generator adapter mode. Default off; file reads agent_generator_output JSON only.",
		}),
	),
	agent_generator_output: Type.Optional(
		Type.String({
			description: "JSON file produced by an external Agent/LLM generator when agent_generator_mode=file.",
		}),
	),
	mode: Type.Optional(
		Type.Union([Type.Literal("suggest"), Type.Literal("dry_run"), Type.Literal("paper")], {
			description:
				"Loop mode. Default dry_run writes candidates and backtests; paper may activate current only when promotion gates pass.",
		}),
	),
	run_id: Type.Optional(Type.String({ description: "Optional fixed run id for reproducible runs" })),
	previous_rejected_reasons: Type.Optional(
		Type.String({ description: "Optional rejected reasons from a previous loop, comma/semicolon separated" }),
	),
	previous_paper_report: Type.Optional(
		Type.String({ description: "Optional previous paper report JSON object or artifact path" }),
	),
	previous_risk_summary: Type.Optional(
		Type.String({ description: "Optional previous risk summary JSON object or artifact path" }),
	),
	previous_repair_guidance: Type.Optional(
		Type.String({ description: "Optional previous repair guidance JSON list/object or comma/semicolon separated text" }),
	),
	include_news: Type.Optional(
		Type.Boolean({ description: "Optionally include read-only news context; default false" }),
	),
	news_limit: Type.Optional(Type.Number({ description: "Max news articles when include_news is true" })),
	news_since_minutes: Type.Optional(Type.Number({ description: "News lookback minutes when include_news is true" })),
});

export function registerStrategyEvolveTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_strategy_evolve",
		label: "Trade Strategy Evolve",
		description:
			"E4/E5 strategy evolve: generate or consume Agent candidate YAMLs, optionally read an explicit file-based Agent generator output, write prompt/feedback/handoff artifacts, expose context health, next action, and submission hints, then suggest/dry_run/paper according to mode.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const days = Math.max(1, Math.floor(params.days ?? 7));
			const candidateCount = Math.max(2, Math.min(3, Math.floor(params.candidate_count ?? 2)));
			const args = [
				"--strategy",
				params.strategy,
				"--symbol",
				params.symbol,
				"--days",
				String(days),
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
			if (params.agent_candidates) {
				args.push("--agent-candidates", params.agent_candidates);
			}
			if (params.agent_generator_mode) {
				args.push("--agent-generator-mode", params.agent_generator_mode);
			}
			if (params.agent_generator_output) {
				args.push("--agent-generator-output", params.agent_generator_output);
			}
			if (params.previous_rejected_reasons) {
				args.push("--previous-rejected-reasons", params.previous_rejected_reasons);
			}
			if (params.previous_paper_report) {
				args.push("--previous-paper-report", params.previous_paper_report);
			}
			if (params.previous_risk_summary) {
				args.push("--previous-risk-summary", params.previous_risk_summary);
			}
			if (params.previous_repair_guidance) {
				args.push("--previous-repair-guidance", params.previous_repair_guidance);
			}
			if (params.include_news) {
				args.push("--include-news");
				args.push("--news-limit", String(Math.max(1, Math.min(20, Math.floor(params.news_limit ?? 5)))));
				args.push("--news-since-minutes", String(Math.max(1, Math.floor(params.news_since_minutes ?? 240))));
			}

			const result = await runTradeScript("tradecat_strategy_evolve.py", args, {
				timeoutMs: 300_000,
			});
			const data = payloadData(result.payload);
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: {
					strategy: params.strategy,
					symbol: params.symbol,
					days,
					candidateCount,
					mode: params.mode ?? "dry_run",
					runId: params.run_id,
					hasAgentCandidates: Boolean(params.agent_candidates),
					agentGeneratorMode: params.agent_generator_mode ?? "off",
					hasAgentGeneratorOutput: Boolean(params.agent_generator_output),
					hasPreviousRiskSummary: Boolean(params.previous_risk_summary),
					hasPreviousRepairGuidance: Boolean(params.previous_repair_guidance),
					includeNews: Boolean(params.include_news),
					agentArtifacts: {
						agentPrompt: field(data, "agent_prompt"),
						agentFeedback: field(data, "agent_feedback"),
						agentHandoff: field(data, "agent_handoff"),
						agentResponseTemplate: field(data, "agent_response_template"),
						agentResponse: field(data, "agent_response"),
						agentResponseValidation: field(data, "agent_response_validation"),
						agentGenerator: field(data, "agent_generator"),
					},
					contextHealth: field(data, "context_health"),
					agentNextAction: field(data, "agent_next_action"),
					agentSubmission: field(data, "agent_submission"),
				},
			};
		},
	});
}
