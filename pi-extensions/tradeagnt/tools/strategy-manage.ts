import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	action: Type.Union(
		[
			Type.Literal("read"),
			Type.Literal("validate"),
			Type.Literal("write"),
			Type.Literal("list"),
			Type.Literal("use"),
			Type.Literal("history"),
		],
		{ description: "Action: read, validate, write, list, use, history" },
	),
	strategy: Type.Optional(
		Type.String({
			description:
				'Strategy name or path (e.g. "current/fast_1m.yaml" or "agent_BTC_USDT.yaml"). Required for read/write/history and one use mode.',
		}),
	),
	release_id: Type.Optional(
		Type.String({
			description:
				"Existing release id to activate with use action. Use either strategy or release_id, not both.",
		}),
	),
	content: Type.Optional(
		Type.String({
			description:
				"YAML content for validate/write action. Must be valid StrategyConfig YAML with name, market, symbols, timeframe, indicators, rules.",
		}),
	),
	note: Type.Optional(
		Type.String({ description: "Note for version history (used with write/use action)." }),
	),
	dry_run: Type.Optional(
		Type.Boolean({
			description: "For write action: validate and resolve path without writing.",
		}),
	),
});

export function registerStrategyManageTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_strategy_manage",
		label: "Trade Strategy Manage",
		description:
			"Safely manage trading strategy YAML files under config/strategies. Actions: read, validate, write with schema validation, list, use by snapshot/release, history. Use this as the only path for agent-created strategies.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const args = [params.action];

			if (params.strategy) {
				args.push("--strategy", params.strategy);
			}
			if (params.release_id) {
				args.push("--release-id", params.release_id);
			}
			if (params.content) {
				args.push("--content", params.content);
			}
			if (params.note) {
				args.push("--note", params.note);
			}
			if (params.dry_run) {
				args.push("--dry-run");
			}

			const result = await runTradeScript("tradecat_strategy_manage.py", args, {
				timeoutMs: 30_000,
			});
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { action: params.action, strategy: params.strategy },
			};
		},
	});
}
