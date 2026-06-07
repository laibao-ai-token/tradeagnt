import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { formatToolText, runTradeScript } from "../run-python.js";

const Params = Type.Object({
	thesis_json: Type.String({ description: "Full agent_trade_thesis.v1 JSON string" }),
});

export function registerSubmitTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "trade_submit_thesis",
		label: "Trade Submit Thesis",
		description:
			"Submit agent_trade_thesis.v1 through fail-closed gates to local paper trading. Requires paper_intent sizing for LONG/SHORT. Human should adopt (R2) before calling.",
		parameters: Params,
		async execute(_toolCallId, params) {
			const dir = mkdtempSync(join(tmpdir(), "tradeagnt-thesis-"));
			const inputPath = join(dir, "thesis.json");
			writeFileSync(inputPath, params.thesis_json, "utf8");
			const result = await runTradeScript("tradecat_agent_submit_thesis.py", ["--input", inputPath], {
				timeoutMs: 90_000,
			});
			return {
				content: [{ type: "text", text: formatToolText(result) }],
				details: { exitCode: result.exitCode },
			};
		},
	});
}
