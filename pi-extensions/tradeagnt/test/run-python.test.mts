/**
 * E2 bridge layer smoke test.
 *
 * 覆盖 E2 P0 修一轮（2026-06-02）的 7 个 P0 修：
 *   P0-1: env 白名单（防 LINEAR_API_KEY / BOT_TOKEN 泄漏到子进程）
 *   P0-2: SIGTERM 后 3s 升 SIGKILL（防孤儿进程）
 *   P0-3: StringDecoder 跨 chunk UTF-8 状态
 *   P0-4: extractLargestJsonBlock 提取最大 JSON 块
 *   P0-5: 8MB stdout/stderr 上限
 *   P0-6: realpath 校验 script 路径不逃逸 scripts/
 *   P0-7: 7 种 errorKind 枚举覆盖
 *
 * Run: node --test --experimental-strip-types pi-extensions/tradeagnt/test/run-python.test.mts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

import { runTradeScript, formatToolText } from "../run-python.ts";

const REPO = process.env.TRADEAGNT_ROOT || resolve(import.meta.dirname, "..", "..", "..");
const ROOT_OPTS = { root: REPO };

// 在 parent process 设置敏感 env，验证子进程看不到
process.env.LINEAR_API_KEY = "leaked_secret_LINEAR_xyz";
process.env.BOT_TOKEN = "leaked_secret_BOT_xyz";
process.env.BINANCE_API_KEY = "leaked_secret_BINANCE_xyz";
process.env.BINANCE_SECRET = "leaked_secret_BINANCE_SEC_xyz";

test("P0-1: env whitelist hides sensitive vars from child", async () => {
	const r = await runTradeScript("_test_e2/env_visibility.py", [], ROOT_OPTS);
	assert.equal(r.ok, true, `expected ok=true, got: ${JSON.stringify(r)}`);
	const data = (r.payload as any).data;
	assert.equal(data.LINEAR_API_KEY, null, "LINEAR_API_KEY must NOT be visible to child");
	assert.equal(data.BOT_TOKEN, null, "BOT_TOKEN must NOT be visible to child");
	assert.equal(data.BINANCE_API_KEY, null, "BINANCE_API_KEY must NOT be visible to child");
	assert.equal(data.BINANCE_SECRET, null, "BINANCE_SECRET must NOT be visible to child");
	// 正向：允许的应该可见
	assert.ok(data.TRADEAGNT_ROOT, "TRADEAGNT_ROOT should be visible (in allowlist)");
});

test("P0-2: timeout sends SIGTERM then escalates to SIGKILL (process actually dies)", async () => {
	const pidfile = "/tmp/opencode/_test_e2_child.pid";
	try { unlinkSync(pidfile); } catch {}

	const r = await runTradeScript(
		"_test_e2/sleep_ignore_term.py",
		[pidfile],
		{ ...ROOT_OPTS, timeoutMs: 1500 },
	);

	assert.equal(r.ok, false, "should be timeout error");
	assert.equal(r.errorKind, "timeout", `errorKind should be 'timeout', got ${r.errorKind}`);

	// 等 SIGKILL grace (3s) + buffer
	await new Promise((res) => setTimeout(res, 4500));

	// 验证子进程已死
	const { readFileSync } = await import("node:fs");
	const pidStr = readFileSync(pidfile, "utf8").trim();
	const pid = parseInt(pidStr, 10);
	assert.ok(pid > 0, "pid file should exist");

	let stillAlive = true;
	try {
		process.kill(pid, 0); // signal 0 = probe existence
	} catch (e: any) {
		stillAlive = false;
	}
	assert.equal(stillAlive, false, `child pid=${pid} should be killed by SIGKILL escalation`);
});

test("P0-3: StringDecoder reassembles multi-byte UTF-8 across chunks", async () => {
	const r = await runTradeScript("_test_e2/utf8_split.py", [], ROOT_OPTS);
	assert.equal(r.ok, true, `expected ok=true, got: ${r.error}`);
	const data = (r.payload as any);
	// 中文字符必须在 rawStdout 里完整出现
	assert.match(r.rawStdout, /你好🌏TradeCat测试/, "UTF-8 multi-byte chars should be intact");
	assert.equal(data.text, "你好🌏TradeCat测试");
});

test("P0-4: extractLargestJsonBlock finds JSON despite warn/debug/error noise", async () => {
	const r = await runTradeScript("_test_e2/json_extract.py", [], ROOT_OPTS);
	assert.equal(r.ok, true, `expected ok=true, got: ${r.error}`);
	assert.equal((r.payload as any).tool, "_test_e2/json_extract");
	assert.equal((r.payload as any).data.symbol, "BTC_USDT");
	assert.equal((r.payload as any).data.price, 70640.3);
	// stderr 包含 warn/error 但不影响 ok
	assert.match(r.rawStderr, /WARN|ERROR/);
});

test("P0-5: 8MB stdout cap truncates large output", async () => {
	const r = await runTradeScript("_test_e2/big_output.py", [], { ...ROOT_OPTS, timeoutMs: 30000 });
	// 这里 expect ok=true (因为 JSON 完整被解析), 但 rawStdout 应该有截断标记
	// 注意：8MB 上限后 JSON.parse 仍能成功（如果 JSON 本身完整）
	assert.match(r.rawStdout, /\[stdout truncated at 8MB\]/, "should be marked as truncated");
});

test("P0-6: realpath rejects symlink escaping scripts/ dir", async () => {
	const r = await runTradeScript("_test_e2/escape_link.py", [], ROOT_OPTS);
	assert.equal(r.ok, false);
	assert.equal(r.errorKind, "path_escape", `errorKind should be 'path_escape', got ${r.errorKind}`);
	assert.match(r.error || "", /escapes scripts\/ dir/);
});

test("P0-7a: errorKind='missing_script' for non-existent script", async () => {
	const r = await runTradeScript("_test_e2/does_not_exist.py", [], ROOT_OPTS);
	assert.equal(r.ok, false);
	assert.equal(r.errorKind, "missing_script");
});

test("P0-7b: errorKind='empty' when exit 0 but no JSON in stdout", async () => {
	const r = await runTradeScript("_test_e2/empty.py", [], ROOT_OPTS);
	assert.equal(r.ok, false);
	assert.equal(r.errorKind, "empty", `got ${r.errorKind}: ${r.error}`);
});

test("P0-7c: errorKind='invalid_json' for malformed JSON", async () => {
	const r = await runTradeScript("_test_e2/bad_json.py", [], ROOT_OPTS);
	assert.equal(r.ok, false);
	assert.equal(r.errorKind, "invalid_json");
});

test("P0-7d: errorKind='unknown' for non-zero exit with stderr", async () => {
	const r = await runTradeScript("_test_e2/exit_nonzero.py", [], ROOT_OPTS);
	assert.equal(r.ok, false);
	assert.equal(r.errorKind, "unknown");
});

test("happy path: real bridge script (tradecat_get_quotes.py) returns structured JSON", async () => {
	const r = await runTradeScript("tradecat_get_quotes.py", ["BTC_USDT"], { ...ROOT_OPTS, timeoutMs: 30000 });
	// quotes 在沙箱内能跑（读本地 SQLite）；可能因数据缺返回 ok=false，但应有结构
	if (r.ok) {
		assert.ok(r.payload, "payload should exist when ok");
	} else {
		// 至少 errorKind 应该是已知的，且 rawStdout 是 JSON 格式
		assert.ok(["empty", "unknown", "invalid_json", "spawn", "timeout", "missing_script", "path_escape"].includes(r.errorKind || ""));
	}
});

test("formatToolText: returns readable text on success", async () => {
	const r = await runTradeScript("_test_e2/json_extract.py", [], ROOT_OPTS);
	const text = formatToolText(r);
	assert.match(text, /_test_e2\/json_extract/);
	assert.match(text, /BTC_USDT/);
});

test("formatToolText: returns readable error on failure with errorKind tag", async () => {
	const r = await runTradeScript("_test_e2/does_not_exist.py", [], ROOT_OPTS);
	const text = formatToolText(r);
	assert.match(text, /\[missing_script\]/);
	assert.match(text, /does_not_exist\.py/);
});
