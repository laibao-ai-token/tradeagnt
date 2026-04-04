# Fund Read Model

## Scope
- Covers `services-preview/tui-service` only.
- Plan A keeps the default source as direct-fetch via `quote.py`.
- No schema or TimescaleDB tables are introduced in this phase.

## Quote Read Model

For each requested fund symbol on the TUI fund page we depend on the following fields:

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

- Live curves continue to accumulate inside the TUI runtime from `QuotePoller` updates.
- Daily curves are seeded on demand only for the currently selected exchange-traded funds via `DirectFundBridge.fetch_daily_candles()`.
- Off-market funds do not receive historical daily curves under Plan A.

## Symbol Rules

- `SH510300` and `SZ159915` are exchange-traded funds.
- `024389` represents an off-market fund.
- `watchlists.py` stores the normalized request symbol.
- `quote.py` can return a different `quote_symbol` for exchange-traded funds than the request symbol.
- `match_cn_fund_signal()` is the sole matching rule used against `signal_history.db` for fund signals.

## Ownership in Plan A

- Dynamic fund universe reload remains owned by `tui.py`.
- `+/-` watchlist edits remain owned by `tui.py`.
- Direct-fetch remains the default fallback path.

## Manual Verification Matrix

### Command 1: direct bridge smoke

```bash
cd /home/tradecat
python scripts/tradecat_get_quotes.py --market cn_fund SH510300 SZ159915 024389
```

Expected:
- `SH510300` (or `510300`) returns a valid quote payload.
- `SZ159915` (or `159915`) returns a valid quote payload.
- `024389` returns an off-market fund quote.

### Command 2: TUI fund page smoke

```bash
cd /home/tradecat/services-preview/tui-service
./scripts/start.sh run --view market_fund_cn --fund-cn-symbols SH510300,SZ159915,024389
```

Expected:
- Fund page opens successfully.
- ETF quotes render correctly.
- Off-market fund quote renders correctly.
- The selected ETF receives a daily curve.
- Switching domain and using `+/-` do not crash the view.
