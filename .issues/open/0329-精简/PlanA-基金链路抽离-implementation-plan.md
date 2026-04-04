# 基金链路抽离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改数据库 schema、不切换默认启动语义的前提下，把 `tui-service` 基金链路整理出清晰的符号语义、直接数据桥接层和可验证的读模型边界，为后续 `collector-service` 接入留出稳定 seam。

**Architecture:** 先把 `cn_fund` 的 symbol 归一化、signal 匹配和场内/场外分流从 `watchlists.py` / `quote.py` / `tui.py` 的重复逻辑中提出来，再引入一个仅服务于 TUI 的 `DirectFundBridge`，把“当前直连抓取”包装成显式 read-model/provider seam。TUI 继续保留现有直连行为和 fallback，只是改为通过 bridge 调 daily curve 补种与基金匹配逻辑，最后再用文档固定 read model 和人工验证矩阵。

**Tech Stack:** Python 3.12, unittest/pytest, curses TUI helpers, existing `services-preview/tui-service/src/*.py`, read-only bridge command `scripts/tradecat_get_quotes.py`

---

## Scope Guardrails

本计划默认遵守以下边界：

1. 不修改 `config/.env`
2. 不执行任何 DDL 或 schema 变更
3. 不删除 `quote.py` 中现有场内/场外基金直连抓取逻辑
4. 不把基金页默认数据源切到数据库
5. 不改根目录 `./scripts/start.sh` 的默认语义
6. 不触碰 `_deprecated/`、`.gitignore` 或旧服务目录迁移

---

## File Map

### Create

- `services-preview/tui-service/src/fund_symbols.py`
  - 集中管理 `cn_fund` 的单个 symbol 归一化、watchlist 归一化、场内候选推断、signal 匹配
- `services-preview/tui-service/src/fund_bridge.py`
  - 为 TUI 基金页提供显式 read-model 和 direct source adapter
- `services-preview/tui-service/tests/test_fund_symbols.py`
  - 覆盖 `cn_fund` 的 symbol 规则和 signal 匹配
- `services-preview/tui-service/tests/test_fund_bridge.py`
  - 覆盖 direct bridge 的 quote/daily curve 行为和 curve seed helper
- `docs/analysis/fund_read_model.md`
  - 固化基金读模型、曲线策略、symbol 规范、回退规则、人工验证矩阵

### Modify

- `services-preview/tui-service/src/watchlists.py`
  - 保留现有公开函数名，但把基金 symbol 归一化委托给 `fund_symbols.py`
- `services-preview/tui-service/src/quote.py`
  - 复用共享基金 symbol helper，避免重复逻辑漂移
- `services-preview/tui-service/src/tui.py`
  - 用共享基金匹配逻辑替换内联实现；用 `DirectFundBridge` 替换基金 daily curve 补种路径
- `services-preview/tui-service/tests/test_quote.py`
  - 保留现有行为测试，并补一条基金 signal 匹配回归测试

---

## Task 1: 集中基金 Symbol 语义

**Files:**
- Create: `services-preview/tui-service/src/fund_symbols.py`
- Modify: `services-preview/tui-service/src/watchlists.py`
- Modify: `services-preview/tui-service/src/quote.py`
- Modify: `services-preview/tui-service/src/tui.py`
- Test: `services-preview/tui-service/tests/test_fund_symbols.py`
- Test: `services-preview/tui-service/tests/test_quote.py`

- [ ] **Step 1: 写失败测试，锁定 `cn_fund` 的统一规则**

```python
# services-preview/tui-service/tests/test_fund_symbols.py
import unittest


class TestFundSymbols(unittest.TestCase):
    def test_normalize_cn_fund_symbol_supports_exchange_and_offmarket(self) -> None:
        from src.fund_symbols import normalize_cn_fund_symbol

        self.assertEqual(normalize_cn_fund_symbol("SH510300"), "SH510300")
        self.assertEqual(normalize_cn_fund_symbol("159915"), "159915")
        self.assertEqual(normalize_cn_fund_symbol("024389"), "024389")
        self.assertEqual(normalize_cn_fund_symbol("021490.SZ"), "SZ021490")

    def test_normalize_cn_fund_symbols_csv_keeps_mixed_watchlist(self) -> None:
        from src.fund_symbols import normalize_cn_fund_symbols_csv

        self.assertEqual(
            normalize_cn_fund_symbols_csv("510300,159915,SH512100,024389,021490.SZ"),
            ["510300", "159915", "SH512100", "024389", "SZ021490"],
        )

    def test_exchange_candidates_infer_exchange_from_raw_code(self) -> None:
        from src.fund_symbols import cn_fund_exchange_candidates

        self.assertEqual(cn_fund_exchange_candidates("510300"), ["SH510300"])
        self.assertEqual(cn_fund_exchange_candidates("159915"), ["SZ159915"])
        self.assertEqual(cn_fund_exchange_candidates("024389"), [])

    def test_match_cn_fund_signal_supports_exchange_and_offmarket(self) -> None:
        from src.fund_symbols import match_cn_fund_signal

        self.assertTrue(match_cn_fund_signal("510300", "SH510300"))
        self.assertTrue(match_cn_fund_signal("SH510300", "SH510300"))
        self.assertTrue(match_cn_fund_signal("024389", "024389"))
        self.assertFalse(match_cn_fund_signal("024389", "SH510300"))
        self.assertFalse(match_cn_fund_signal("SH510300", "SZ159915"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认当前仓库还没有共享基金语义模块**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_fund_symbols.py -q
```

Expected:

```text
E   ModuleNotFoundError: No module named 'src.fund_symbols'
```

- [ ] **Step 3: 创建共享基金 symbol 模块**

```python
# services-preview/tui-service/src/fund_symbols.py
from __future__ import annotations


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_cn_fund_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace("/", "").replace("-", "").replace("_", "")
    if s.endswith(".SH"):
        s = "SH" + s[:-3]
    elif s.endswith(".SZ"):
        s = "SZ" + s[:-3]
    if s.startswith(("SH", "SZ")):
        digits = "".join(ch for ch in s[2:] if ch.isdigit())
        if len(digits) == 6:
            return s[:2] + digits
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        return digits
    return ""


def normalize_cn_fund_symbols_csv(raw: str) -> list[str]:
    out: list[str] = []
    for token in (raw or "").replace(" ", "").split(","):
        normalized = normalize_cn_fund_symbol(token)
        if normalized:
            out.append(normalized)
    return _dedup_keep_order(out)


def cn_fund_exchange_candidates(symbol: str) -> list[str]:
    normalized = normalize_cn_fund_symbol(symbol)
    if not normalized:
        return []
    if normalized.startswith(("SH", "SZ")):
        return [normalized]

    code = normalized
    out: list[str] = []
    if code[0] in {"5", "6", "9"}:
        out.append("SH" + code)
    if code.startswith(("15", "16", "18")):
        out.append("SZ" + code)
    return out


def _fund_digits_key(symbol: str) -> str:
    normalized = normalize_cn_fund_symbol(symbol)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    return digits if len(digits) == 6 else ""


def _normalize_cn_fund_exchange_symbol(symbol: str) -> str:
    normalized = normalize_cn_fund_symbol(symbol)
    if normalized.startswith(("SH", "SZ")):
        return normalized
    candidates = cn_fund_exchange_candidates(normalized)
    return candidates[0] if candidates else ""


def match_cn_fund_signal(signal_symbol: str, quote_symbol: str) -> bool:
    quote_norm = normalize_cn_fund_symbol(quote_symbol)
    signal_norm = normalize_cn_fund_symbol(signal_symbol)
    if not quote_norm or not signal_norm:
        return False

    if quote_norm.startswith(("SH", "SZ")):
        return _normalize_cn_fund_exchange_symbol(signal_norm) == quote_norm

    quote_digits = _fund_digits_key(quote_norm)
    signal_digits = _fund_digits_key(signal_norm)
    if quote_digits:
        return quote_digits == signal_digits
    return False
```

- [ ] **Step 4: 让 `watchlists.py` / `quote.py` / `tui.py` 共用这套规则**

```python
# services-preview/tui-service/src/watchlists.py
from .fund_symbols import normalize_cn_fund_symbols_csv


def normalize_cn_fund_symbols(raw: str) -> list[str]:
    return normalize_cn_fund_symbols_csv(raw)
```

```python
# services-preview/tui-service/src/quote.py
from .fund_symbols import cn_fund_exchange_candidates, normalize_cn_fund_symbol
```

```python
# services-preview/tui-service/src/tui.py
from .fund_symbols import match_cn_fund_signal, normalize_cn_fund_symbol

# delete the local _normalize_cn_fund_symbol() helper after importing the shared version
_normalize_cn_fund_symbol = normalize_cn_fund_symbol
```

```python
# services-preview/tui-service/src/quote.py
# delete the local _normalize_cn_fund_symbol() and _cn_fund_exchange_candidates() helpers
# and update call sites to use the imported shared functions instead
normalized = normalize_cn_fund_symbol(symbol)
candidates = cn_fund_exchange_candidates(normalized)
```

```python
# services-preview/tui-service/src/tui.py


def _match_signal_to_symbol(signal_symbol: str, quote_symbol: str, market: str) -> bool:
    m = (market or "").strip().lower()
    qsym = (quote_symbol or "").strip().upper()
    if not qsym:
        return False
    if m == "crypto_spot":
        return _crypto_signal_symbol_to_pair(signal_symbol) == qsym
    if m == "us_stock":
        return (signal_symbol or "").strip().upper() == qsym
    if m == "hk_stock":
        return _normalize_hk_symbol(signal_symbol) == _normalize_hk_symbol(qsym)
    if m == "cn_stock":
        return _normalize_cn_symbol(signal_symbol) == _normalize_cn_symbol(qsym)
    if m == "cn_fund":
        return match_cn_fund_signal(signal_symbol, qsym)
    return False
```

- [ ] **Step 5: 跑回归测试并提交**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_fund_symbols.py tests/test_quote.py -q
git add src/fund_symbols.py src/watchlists.py src/quote.py src/tui.py tests/test_fund_symbols.py tests/test_quote.py
git commit -m "refactor(tui): centralize cn fund symbol semantics"
```

Expected:

```text
all selected tests passed
[branch] refactor(tui): centralize cn fund symbol semantics
```

---

## Task 2: 添加 TUI 专用基金 Direct Bridge

**Files:**
- Create: `services-preview/tui-service/src/fund_bridge.py`
- Test: `services-preview/tui-service/tests/test_fund_bridge.py`

- [ ] **Step 1: 写失败测试，固定 bridge 的 quote/daily curve 合同**

```python
# services-preview/tui-service/tests/test_fund_bridge.py
import unittest
from unittest.mock import patch


class TestFundBridge(unittest.TestCase):
    def test_fetch_quote_rows_preserves_requested_symbol(self) -> None:
        from src.quote import Quote
        from src.fund_bridge import DirectFundBridge

        fake_quote = Quote(
            symbol="SH510300",
            name="沪深300ETF",
            price=4.321,
            prev_close=4.300,
            open=4.305,
            high=4.330,
            low=4.290,
            currency="CNY",
            volume=12345.0,
            amount=54321.0,
            ts="2026-03-29 10:01:00",
            source="tencent",
        )

        bridge = DirectFundBridge(provider="tencent", market="cn_fund", timeout_s=3.0)
        with patch("src.fund_bridge.fetch_quotes", return_value={"510300": fake_quote}):
            rows = bridge.fetch_quote_rows(["510300"], now_ts=1234.0)

        row = rows["510300"]
        self.assertEqual(row.request_symbol, "510300")
        self.assertEqual(row.quote_symbol, "SH510300")
        self.assertEqual(row.source, "tencent")
        self.assertEqual(row.last_fetch_at, 1234.0)

    def test_fetch_daily_candles_converts_series_to_candles(self) -> None:
        from src.fund_bridge import DirectFundBridge

        bridge = DirectFundBridge(provider="tencent", market="cn_fund", timeout_s=6.0)
        with patch(
            "src.fund_bridge.fetch_daily_curve_1d",
            return_value=[
                (1711526400, 4.10, 4.20, 4.00, 4.18, 1000.0),
                (1711612800, 4.18, 4.25, 4.12, 4.21, 1200.0),
            ],
        ):
            candles = bridge.fetch_daily_candles("SH510300", limit=15)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].ts_open, 1711526400)
        self.assertAlmostEqual(candles[1].close, 4.21, places=6)
        self.assertAlmostEqual(candles[1].notional_est, 1200.0 * 4.21, places=6)

    def test_seed_curve_from_daily_candles_replaces_curve_buffer(self) -> None:
        from collections import deque

        from src.fund_bridge import seed_curve_from_daily_candles
        from src.micro import Candle

        curves: dict[str, deque[Candle]] = {}
        seeded = seed_curve_from_daily_candles(
            curves,
            "SH510300",
            [
                Candle(1, 4.0, 4.1, 3.9, 4.05, 10.0, 40.5),
                Candle(2, 4.05, 4.2, 4.0, 4.18, 12.0, 50.16),
            ],
            max_points=20,
        )

        self.assertTrue(seeded)
        self.assertEqual(len(curves["SH510300"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认 bridge 还不存在**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_fund_bridge.py -q
```

Expected:

```text
E   ModuleNotFoundError: No module named 'src.fund_bridge'
```

- [ ] **Step 3: 创建 `fund_bridge.py`，把当前直连抓取包装成显式 seam**

```python
# services-preview/tui-service/src/fund_bridge.py
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Protocol

from .fund_symbols import normalize_cn_fund_symbol
from .micro import Candle
from .quote import fetch_daily_curve_1d, fetch_quotes


@dataclass(frozen=True)
class FundQuoteRow:
    request_symbol: str
    quote_symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    ts: str
    source: str
    last_fetch_at: float


class FundBridge(Protocol):
    def fetch_quote_rows(self, symbols: list[str], *, now_ts: float | None = None) -> dict[str, FundQuoteRow]:
        ...

    def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
        ...


class DirectFundBridge:
    def __init__(self, *, provider: str, market: str = "cn_fund", timeout_s: float = 6.0) -> None:
        self._provider = (provider or "tencent").strip().lower() or "tencent"
        self._market = (market or "cn_fund").strip().lower() or "cn_fund"
        self._timeout_s = max(1.0, float(timeout_s))

    def fetch_quote_rows(self, symbols: list[str], *, now_ts: float | None = None) -> dict[str, FundQuoteRow]:
        normalized = [normalize_cn_fund_symbol(item) for item in (symbols or [])]
        requested = [item for item in normalized if item]
        if not requested:
            return {}

        fetched_at = float(now_ts) if now_ts is not None and now_ts > 0 else time.time()
        raw_quotes = fetch_quotes(
            provider=self._provider,
            market=self._market,
            symbols=requested,
            timeout_s=self._timeout_s,
        )

        out: dict[str, FundQuoteRow] = {}
        for request_symbol in requested:
            quote = raw_quotes.get(request_symbol)
            if quote is None:
                continue
            out[request_symbol] = FundQuoteRow(
                request_symbol=request_symbol,
                quote_symbol=(quote.symbol or request_symbol).strip().upper() or request_symbol,
                name=(quote.name or request_symbol).strip() or request_symbol,
                price=float(quote.price),
                prev_close=float(quote.prev_close),
                open=float(quote.open),
                high=float(quote.high),
                low=float(quote.low),
                volume=float(quote.volume),
                amount=float(quote.amount),
                ts=(quote.ts or "").strip(),
                source=(quote.source or "").strip() or "direct",
                last_fetch_at=fetched_at,
            )
        return out

    def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
        request_symbol = normalize_cn_fund_symbol(symbol)
        if not request_symbol:
            return []

        rows = fetch_daily_curve_1d(
            provider=self._provider,
            market=self._market,
            symbol=request_symbol,
            timeout_s=self._timeout_s,
            limit=max(5, int(limit)),
        )
        out: list[Candle] = []
        for ts_open, open_px, high_px, low_px, close_px, volume in rows:
            out.append(
                Candle(
                    ts_open=int(ts_open),
                    open=float(open_px),
                    high=float(high_px),
                    low=float(low_px),
                    close=float(close_px),
                    volume_est=float(volume),
                    notional_est=float(volume) * float(close_px) if float(volume) > 0 else 0.0,
                )
            )
        return out


def seed_curve_from_daily_candles(
    curves: dict[str, deque[Candle]],
    symbol: str,
    candles: list[Candle],
    *,
    max_points: int,
) -> bool:
    request_symbol = normalize_cn_fund_symbol(symbol)
    if not request_symbol or not candles:
        return False

    buffer: deque[Candle] = deque(maxlen=max(5, int(max_points)))
    for candle in candles[-max_points:]:
        buffer.append(candle)
    if not buffer:
        return False

    curves[request_symbol] = buffer
    return True
```

- [ ] **Step 4: 跑新测试和既有 quote 回归**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_fund_bridge.py tests/test_quote.py::TestTencentQuoteParse::test_fetch_quote_cn_fund_falls_back_to_offmarket -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: 提交 bridge 切片**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
git add src/fund_bridge.py tests/test_fund_bridge.py
git commit -m "feat(tui): add direct fund bridge seam"
```

Expected:

```text
[branch] feat(tui): add direct fund bridge seam
```

---

## Task 3: 让 TUI 基金页走共享匹配逻辑和 Bridge 曲线补种

**Files:**
- Modify: `services-preview/tui-service/src/tui.py`
- Modify: `services-preview/tui-service/tests/test_quote.py`

- [ ] **Step 1: 先补 TUI 回归测试，锁定基金信号匹配和 daily curve 补种行为**

```python
# append to services-preview/tui-service/tests/test_quote.py
    def test_match_signal_to_symbol_cn_fund_supports_exchange_and_offmarket(self) -> None:
        from src.tui import _match_signal_to_symbol

        self.assertTrue(_match_signal_to_symbol("510300", "SH510300", "cn_fund"))
        self.assertTrue(_match_signal_to_symbol("024389", "024389", "cn_fund"))
        self.assertFalse(_match_signal_to_symbol("024389", "SH510300", "cn_fund"))

    def test_maybe_seed_fund_curve_from_daily_history_uses_bridge(self) -> None:
        from collections import deque

        from src.micro import Candle
        from src.tui import _maybe_seed_fund_curve_from_daily_history

        class _FakeBridge:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
                self.calls.append((symbol, limit))
                return [
                    Candle(1, 4.0, 4.1, 3.9, 4.05, 10.0, 40.5),
                    Candle(2, 4.05, 4.2, 4.0, 4.18, 12.0, 50.16),
                ]

        curves: dict[str, deque[Candle]] = {}
        bridge = _FakeBridge()

        _maybe_seed_fund_curve_from_daily_history(
            bridge=bridge,
            curves=curves,
            symbols={"SH510300"},
            attempts={},
            now_ts=1_711_710_000.0,
            lookback_days=15,
        )

        self.assertEqual(bridge.calls, [("SH510300", 15)])
        self.assertIn("SH510300", curves)
        self.assertEqual(len(curves["SH510300"]), 2)
```

- [ ] **Step 2: 运行测试，确认现有 `tui.py` 还没有 bridge 入口**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_quote.py -q
```

Expected:

```text
TypeError: _maybe_seed_fund_curve_from_daily_history() got an unexpected keyword argument 'bridge'
```

- [ ] **Step 3: 修改 `tui.py`，把基金页的高风险点接到 bridge 上**

```python
# services-preview/tui-service/src/tui.py
from .fund_bridge import DirectFundBridge, seed_curve_from_daily_candles
from .fund_symbols import match_cn_fund_signal, normalize_cn_fund_symbol as _normalize_cn_fund_symbol
```

```python
# inside run() setup block in services-preview/tui-service/src/tui.py
    fund_bridge = DirectFundBridge(
        provider=quote_cfgs.fund_cn.provider,
        market=quote_cfgs.fund_cn.market,
        timeout_s=6.0,
    )
```

```python
# replace the cn_fund branch in _match_signal_to_symbol()
    if m == "cn_fund":
        return match_cn_fund_signal(signal_symbol, qsym)
```

```python
# update the helper signature and implementation
def _maybe_seed_fund_curve_from_daily_history(
    *,
    bridge: DirectFundBridge,
    curves: dict[str, deque[Candle]],
    symbols: set[str],
    attempts: dict[str, float],
    now_ts: float,
    lookback_days: int = 15,
) -> None:
    days = max(5, int(lookback_days))
    target_span_s = max(24 * 3600, (days - 1) * 24 * 3600)

    for symbol in sorted(symbols):
        existing = curves.get(symbol)
        last_try = float(attempts.get(symbol, 0.0) or 0.0)
        if existing is not None and len(existing) >= max(5, days // 2):
            span_s = max(0.0, float(existing[-1].ts_open - existing[0].ts_open))
            if span_s >= target_span_s and (now_ts - last_try) < _FUND_CN_CURVE_REFRESH_SECONDS:
                continue

        if (now_ts - last_try) < _FUND_CN_CURVE_REFRESH_SECONDS:
            continue
        attempts[symbol] = now_ts

        candles = bridge.fetch_daily_candles(symbol, limit=days)
        if not candles:
            continue
        seed_curve_from_daily_candles(
            curves,
            symbol,
            candles,
            max_points=max(20, days * 3),
        )
```

```python
# update the call site near the selected fund logic
            if selected_fund_symbol and selected_fund_symbol.startswith(("SH", "SZ")):
                _maybe_seed_fund_curve_from_daily_history(
                    bridge=fund_bridge,
                    curves=fund_cn_daily_curves,
                    symbols={selected_fund_symbol},
                    attempts=fund_cn_curve_seed_attempts,
                    now_ts=now,
                    lookback_days=_FUND_CN_CURVE_DAYS,
                )
```

- [ ] **Step 4: 运行基金页相关回归测试**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
pytest tests/test_fund_symbols.py tests/test_fund_bridge.py tests/test_quote.py tests/test_etf_selector.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: 提交 TUI 整合切片**

Run:

```bash
cd /home/tradecat/services-preview/tui-service
git add src/tui.py tests/test_quote.py
git commit -m "refactor(tui): route fund page through shared bridge"
```

Expected:

```text
[branch] refactor(tui): route fund page through shared bridge
```

---

## Task 4: 固化基金读模型与人工验证矩阵

**Files:**
- Create: `docs/analysis/fund_read_model.md`

- [ ] **Step 1: 新建读模型文档，明确 Plan A 只保留 direct source**

```markdown
# Fund Read Model

## Scope

- This document covers `services-preview/tui-service` only.
- The default source remains direct-fetch (`quote.py`) in Plan A.
- No schema or TimescaleDB table is required in this phase.
```

- [ ] **Step 2: 写清 quote/daily curve/read-side 合同**

```markdown
## Quote Read Model

For each requested fund symbol, the TUI fund page depends on:

- `request_symbol`
- `quote_symbol`
- `name`
- `price`
- `prev_close`
- `open`
- `high`
- `low`
- `volume`
- `amount`
- `ts`
- `source`
- `last_fetch_at`

## Curve Strategy

- Live curve: still accumulated in TUI runtime from `QuotePoller`.
- Daily curve: seeded on demand for the selected exchange-traded fund through `DirectFundBridge.fetch_daily_candles()`.
- Off-market funds do not gain historical daily curves in Plan A.
```

- [ ] **Step 3: 写清 symbol 规范、fallback 和动态 watchlist 所有权**

```markdown
## Symbol Rules

- `SH510300` / `SZ159915`: exchange-traded funds
- `024389`: off-market fund code
- `watchlists.py` stores the normalized request symbol
- `quote.py` may return a different `quote_symbol` for exchange-traded entries
- `match_cn_fund_signal()` is the single matching rule for `signal_history.db`

## Ownership in Plan A

- Dynamic fund universe reload remains owned by `tui.py`
- `+/-` watchlist edits remain owned by `tui.py`
- Direct-fetch remains the default fallback path
```

- [ ] **Step 4: 补人工验证矩阵，并把命令写死**

```markdown
## Manual Verification Matrix

### Command 1: direct bridge smoke

~~~bash
cd /home/tradecat
python scripts/tradecat_get_quotes.py --market cn_fund SH510300 SZ159915 024389
~~~

Expected:

- `SH510300` or `510300` returns a valid quote payload
- `SZ159915` or `159915` returns a valid quote payload
- `024389` returns an off-market fund quote

### Command 2: TUI fund page smoke

~~~bash
cd /home/tradecat/services-preview/tui-service
./scripts/start.sh run --view market_fund_cn --fund-cn-symbols SH510300,SZ159915,024389
~~~

Expected:

- fund page opens successfully
- ETF quotes render
- off-market fund quote renders
- selected ETF gets a daily curve
- no crash when switching domain or using `+/-`
```

- [ ] **Step 5: 提交文档切片**

Run:

```bash
cd /home/tradecat
git add docs/analysis/fund_read_model.md
git commit -m "docs: define fund read model and verification matrix"
```

Expected:

```text
[branch] docs: define fund read model and verification matrix
```

---

## Execution Order

按顺序执行，不要并行改同一文件：

1. Task 1
2. Task 2
3. Task 3
4. Task 4

可以并行的点只有：

1. Task 1 的测试草稿和文档草稿可以并行起草
2. Task 4 可在 Task 3 代码稳定后由单独 agent 负责文档整理

---

## Acceptance Checklist

全部完成后必须满足：

1. `pytest tests/test_fund_symbols.py tests/test_fund_bridge.py tests/test_quote.py tests/test_etf_selector.py -q` 通过
2. `python scripts/tradecat_get_quotes.py --market cn_fund SH510300 SZ159915 024389` 能返回非空样本
3. `./scripts/start.sh run --view market_fund_cn --fund-cn-symbols SH510300,SZ159915,024389` 人工验证通过
4. 没有新增 schema 依赖
5. `quote.py` 的场外基金 fallback 仍然可用
6. `signal_history.db` 的基金 symbol 匹配不回归

---

## Out of Scope Reminder

以下内容明确不属于本计划：

1. TimescaleDB 基金表设计
2. `collector-service` 创建
3. 默认基金数据源切换到数据库
4. `_deprecated/` 清理
5. 根脚本默认命令变更

---

## Handoff

Plan complete and saved to `.issues/open/0329-精简/PlanA-基金链路抽离-implementation-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
