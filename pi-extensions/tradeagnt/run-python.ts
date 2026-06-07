/**
 * Run tradeagnt Python bridge scripts and return parsed JSON.
 *
 * Hardening (E2 P0 review 2026-06-02):
 *   - env 白名单 (防 DATABASE_URL / LINEAR_API_KEY / BOT_TOKEN 泄漏到 LLM)
 *   - SIGTERM 后 SIGKILL 升级 (防孤儿进程)
 *   - StringDecoder 跨 chunk UTF-8 状态 (A 股/港股中文名)
 *   - extractLargestJsonBlock 提取最大 JSON 块 (防 print(warn) 污染)
 *   - 8MB stdout/stderr 上限 (防 OOM)
 *   - realpath 校验 script 路径不逃逸 scripts/ (防路径遍历/软链绕过)
 *   - 失败时返回 errorKind 便于 Agent 重试
 */
import { spawn } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DEFAULT_TIMEOUT_MS = 30_000;
const QUOTES_TIMEOUT_MS = 60_000;
const INDICATORS_TIMEOUT_MS = 60_000;
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024; // 8 MB
const MAX_JSON_CHARS = 48_000;
const SIGKILL_GRACE_MS = 3_000;

/**
 * Env 白名单：子进程可继承的变量。
 * 显式排除 LINEAR_API_KEY / BOT_TOKEN / BINANCE_API_KEY 等敏感密钥。
 */
const ENV_ALLOWLIST = new Set([
	"PATH",
	"HOME",
	"LANG",
	"LC_ALL",
	"TZ",
	"USER",
	"TMPDIR",
	// tradeagnt 控制
	"TRADEAGNT_ROOT",
	"TRADEAGNT_DATA_DIR",
	"TRADEAGNT_PYTHON",
	"TRADEAGNT_FRESHNESS_SEC",
	"TRADEAGNT_AGENT_MODE",
	"TRADEAGNT_AGENT_CONFLICT",
	"TRADEAGNT_HARNESS_V1",
	"TRADEAGNT_EXEC_MODE",
	"TRADEAGNT_LAYOUT",
	"TRADEAGNT_TMUX_SESSION",
	// DB / 网络 (Python 脚本可能需要)
	"DATABASE_URL",
	"HTTP_PROXY",
	"HTTPS_PROXY",
	"NO_PROXY",
	"http_proxy",
	"https_proxy",
	"no_proxy",
	"ALTERNATIVE_DB_SCHEMA",
	// TUI / 信号配置
	"DEFAULT_LOCALE",
	"SIGNAL_DATA_MAX_AGE",
	"COOLDOWN_SECONDS",
	"TUI_SIGNAL_STRATEGY",
	"TUI_SIGNAL_STRATEGY_EXTRA",
	"TUI_SIGNAL_POLLER",
	"PAPER_AUTO_MARKET",
	"SYMBOLS_GROUPS",
	"SYMBOLS_EXTRA",
	"SYMBOLS_EXCLUDE",
	// 显式 NOT included: LINEAR_API_KEY, BOT_TOKEN, *_API_KEY, *_SECRET
]);

function buildChildEnv(root: string): NodeJS.ProcessEnv {
	const filtered: NodeJS.ProcessEnv = {};
	for (const [k, v] of Object.entries(process.env)) {
		if (ENV_ALLOWLIST.has(k)) {
			filtered[k] = v;
		}
	}
	filtered.TRADEAGNT_ROOT = root;
	return filtered;
}

export type TradeScriptErrorKind =
	| "spawn"
	| "timeout"
	| "empty"
	| "invalid_json"
	| "missing_script"
	| "path_escape"
	| "unknown";

export type TradeScriptResult = {
	ok: boolean;
	payload: Record<string, unknown> | null;
	rawStdout: string;
	rawStderr: string;
	exitCode: number | null;
	error?: string;
	errorKind?: TradeScriptErrorKind;
};

export function resolveTradeagntRoot(): string {
	const fromEnv = (process.env.TRADEAGNT_ROOT || "").trim();
	if (fromEnv) {
		const r = resolve(fromEnv);
		validateRepoRoot(r, "TRADEAGNT_ROOT");
		return r;
	}
	// pi-extensions/tradeagnt → tradeagnt repo root
	const r = resolve(__dirname, "..", "..");
	validateRepoRoot(r, "(inferred)");
	return r;
}

function validateRepoRoot(r: string, source: string): void {
	if (!existsSync(join(r, "pyproject.toml")) || !existsSync(join(r, "scripts"))) {
		throw new Error(
			`${source} points to '${r}', which is not a valid tradeagnt repo (missing pyproject.toml or scripts/)`,
		);
	}
}

export function resolvePythonBin(root: string): string {
	const venvPy = join(root, ".venv", "bin", "python");
	if (existsSync(venvPy)) {
		return venvPy;
	}
	const venvPy3 = join(root, ".venv", "bin", "python3");
	if (existsSync(venvPy3)) {
		return venvPy3;
	}
	return process.env.TRADEAGNT_PYTHON || "python3";
}

function truncateJsonText(text: string): string {
	if (text.length <= MAX_JSON_CHARS) {
		return text;
	}
	// 截断在最后一个完整 } 或 ] 后，避免切 JSON 字符串
	const cut = text.slice(0, MAX_JSON_CHARS);
	const lastClose = Math.max(cut.lastIndexOf("}"), cut.lastIndexOf("]"));
	if (lastClose > 0) {
		return `${cut.slice(0, lastClose + 1)}\n…[truncated ${text.length - lastClose - 1} chars]`;
	}
	return `${cut}\n…[truncated ${text.length - MAX_JSON_CHARS} chars]`;
}

/** 从 stdout 中提取最大 JSON 块（首尾花括号/方括号） */
function extractLargestJsonBlock(text: string): string | null {
	const trimmed = text.trim();
	if (!trimmed) {
		return null;
	}
	if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
		return trimmed;
	}
	const firsts = [trimmed.indexOf("{"), trimmed.indexOf("[")].filter((i) => i >= 0);
	if (firsts.length === 0) {
		return null;
	}
	const first = Math.min(...firsts);
	const last = Math.max(trimmed.lastIndexOf("}"), trimmed.lastIndexOf("]"));
	if (last <= first) {
		return null;
	}
	return trimmed.slice(first, last + 1);
}

export type RunScriptOpts = {
	timeoutMs?: number;
	root?: string;
	kind?: "quotes" | "indicators" | "news" | "default";
};

export function runTradeScript(
	scriptRel: string,
	args: string[] = [],
	opts?: RunScriptOpts,
): Promise<TradeScriptResult> {
	let root: string;
	try {
		root = opts?.root ?? resolveTradeagntRoot();
	} catch (err) {
		return Promise.resolve({
			ok: false,
			payload: null,
			rawStdout: "",
			rawStderr: "",
			exitCode: null,
			error: String(err),
			errorKind: "missing_script",
		});
	}

	const python = resolvePythonBin(root);
	const scriptPath = join(root, "scripts", scriptRel);

	if (!existsSync(scriptPath)) {
		return Promise.resolve({
			ok: false,
			payload: null,
			rawStdout: "",
			rawStderr: "",
			exitCode: null,
			error: `script not found: ${scriptPath}`,
			errorKind: "missing_script",
		});
	}

	// realpath 校验 script 确实在 scripts/ 下（防路径遍历/软链绕过）
	try {
		const realScript = realpathSync(scriptPath);
		const realScriptsDir = realpathSync(join(root, "scripts"));
		if (!realScript.startsWith(realScriptsDir + sep)) {
			return Promise.resolve({
				ok: false,
				payload: null,
				rawStdout: "",
				rawStderr: "",
				exitCode: null,
				error: `script escapes scripts/ dir: ${realScript}`,
				errorKind: "path_escape",
			});
		}
	} catch (err) {
		return Promise.resolve({
			ok: false,
			payload: null,
			rawStdout: "",
			rawStderr: "",
			exitCode: null,
			error: `realpath failed: ${String(err)}`,
			errorKind: "missing_script",
		});
	}

	const timeoutMs = opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

	return new Promise((resolvePromise) => {
		let child;
		try {
			child = spawn(python, [scriptPath, ...args], {
				cwd: root,
				env: buildChildEnv(root),
				stdio: ["ignore", "pipe", "pipe"],
			});
		} catch (err) {
			resolvePromise({
				ok: false,
				payload: null,
				rawStdout: "",
				rawStderr: "",
				exitCode: null,
				error: `spawn failed: ${String(err)}`,
				errorKind: "spawn",
			});
			return;
		}

		// StringDecoder 维护跨 chunk UTF-8 状态
		const stdoutDecoder = new StringDecoder("utf8");
		const stderrDecoder = new StringDecoder("utf8");
		let stdout = "";
		let stderr = "";
		let stdoutBytes = 0;
		let stderrBytes = 0;
		let stdoutTruncated = false;
		let settled = false;
		let killEscalateTimer: NodeJS.Timeout | null = null;

		// 统一构建 result：rawStdout 反映当前 stdout（含截断 marker）
		const buildResult = (
			overrides: Partial<TradeScriptResult>,
		): TradeScriptResult => {
			const stdoutFinal =
				stdoutTruncated && !stdout.endsWith("[stdout truncated at 8MB]")
					? stdout + "\n…[stdout truncated at 8MB]"
					: stdout;
			return {
				ok: false,
				payload: null,
				rawStdout: stdoutFinal,
				rawStderr: stderr,
				exitCode: null,
				...overrides,
			};
		};

		const finish = (result: TradeScriptResult) => {
			if (settled) {
				return;
			}
			settled = true;
			clearTimeout(timer);
			stdout += stdoutDecoder.end();
			stderr += stderrDecoder.end();
			resolvePromise(result);
		};

		const timer = setTimeout(() => {
			child.kill("SIGTERM");
			finish(
				buildResult({
					error: `timeout after ${timeoutMs}ms (SIGTERM sent; SIGKILL in ${SIGKILL_GRACE_MS}ms)`,
					errorKind: "timeout",
				}),
			);
			// SIGKILL 升级（即使 close 不会再 fire 也要保底）
			killEscalateTimer = setTimeout(() => {
				try {
					child.kill("SIGKILL");
				} catch {
					// child 可能已退出
				}
			}, SIGKILL_GRACE_MS);
		}, timeoutMs);

		child.stdout?.on("data", (chunk: Buffer) => {
			stdoutBytes += chunk.length;
			if (stdoutBytes > MAX_OUTPUT_BYTES) {
				if (!stdoutTruncated) {
					stdoutTruncated = true;
					try {
						child.stdout?.destroy();
					} catch {
						// ignore
					}
				}
				return;
			}
			stdout += stdoutDecoder.write(chunk);
		});
		child.stderr?.on("data", (chunk: Buffer) => {
			stderrBytes += chunk.length;
			if (stderrBytes > MAX_OUTPUT_BYTES) {
				try {
					child.stderr?.destroy();
				} catch {
					// ignore
				}
				return;
			}
			stderr += stderrDecoder.write(chunk);
		});

		child.on("error", (err) => {
			finish(
				buildResult({
					error: `spawn error: ${String(err)}`,
					errorKind: "spawn",
				}),
			);
		});

		child.on("close", (code) => {
			if (killEscalateTimer) {
				clearTimeout(killEscalateTimer);
				killEscalateTimer = null;
			}
			const candidate = extractLargestJsonBlock(stdout);
			if (!candidate) {
				// 区分: stdout 真空 vs 有内容但非 JSON
				const stdoutIsEmpty = stdout.trim().length === 0;
				finish(
					buildResult({
						exitCode: code,
						error:
							stderr.trim() ||
							(stdoutIsEmpty
								? "empty stdout (no output from script)"
								: "no JSON block found in non-empty stdout"),
						errorKind:
							code === 0 ? (stdoutIsEmpty ? "empty" : "invalid_json") : "unknown",
					}),
				);
				return;
			}
			try {
				const payload = JSON.parse(candidate) as Record<string, unknown>;
				finish(
					buildResult({
						ok: true,
						payload,
						exitCode: code,
					}),
				);
			} catch (err) {
				finish(
					buildResult({
						exitCode: code,
						error: `invalid json: ${err}`,
						errorKind: "invalid_json",
					}),
				);
			}
		});
	});
}

export function formatToolText(result: TradeScriptResult): string {
	if (result.ok && result.payload) {
		return truncateJsonText(JSON.stringify(result.payload, null, 2));
	}
	const tag = result.errorKind ? `[${result.errorKind}] ` : "";
	const parts = [`${tag}${result.error || "trade script failed"}`];
	if (result.rawStderr.trim()) {
		parts.push(result.rawStderr.trim());
	} else if (result.rawStdout.trim()) {
		parts.push(result.rawStdout.trim().slice(0, 2000));
	}
	return parts.join("\n");
}
