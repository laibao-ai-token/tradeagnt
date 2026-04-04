"""collector-service CLI entrypoint.

Default mode remains a safe status/dry-run payload for CLI and script
compatibility. Real collector execution is enabled explicitly via `--run`.

Note: Keep syntax compatible with `python3 -m py_compile` checks in this repo's tooling.
"""

import argparse
import json
import signal
import sys
import threading
from typing import Optional, Sequence

from src.config import load_config


COLLECTOR_SPECS = (
    ("crypto", ("crypto", "crypto_kline", "crypto_metrics", "crypto-kline", "crypto-metrics"), ("crypto_kline", "crypto_metrics")),
    ("orderbook", ("orderbook", "crypto_orderbook", "crypto-orderbook"), ("crypto_orderbook",)),
    ("equity", ("equity",), ("equity",)),
    ("fund_cn", ("fund_cn", "fund-cn"), ("fund_cn",)),
    ("news", ("news",), ("news",)),
)


class RuntimeState(object):
    """Process runtime state used by signal handlers."""

    def __init__(self):
        self.shutdown_requested = False
        self._shutdown_event = threading.Event()
        self._shutdown_hooks = []

    def request_shutdown(self, signum):
        self.shutdown_requested = True
        self._shutdown_event.set()
        for hook in list(self._shutdown_hooks):
            try:
                hook()
            except Exception as exc:
                sys.stderr.write(
                    "collector-service runtime: shutdown hook failed: {0}\n".format(exc)
                )
        sys.stderr.write(
            "collector-service runtime: shutdown requested via signal {0}.\n".format(signum)
        )

    def add_shutdown_hook(self, hook):
        if callable(hook):
            self._shutdown_hooks.append(hook)

    def wait(self, timeout_seconds):
        try:
            timeout_value = max(0.0, float(timeout_seconds))
        except Exception:
            timeout_value = 0.0
        return self._shutdown_event.wait(timeout_value)


def _split_collectors(raw_value):
    if not raw_value:
        return []

    values = []
    seen = set()
    for chunk in raw_value.split(","):
        name = chunk.strip().lower()
        if not name or name in seen:
            continue
        values.append(name)
        seen.add(name)
    return values


def _known_collectors():
    return [spec[0] for spec in COLLECTOR_SPECS]


def _collector_alias_map():
    aliases = {}
    for cli_name, alias_names, attr_names in COLLECTOR_SPECS:
        del attr_names
        for alias_name in alias_names:
            aliases[alias_name] = cli_name
    return aliases


def _normalize_collector_names(names):
    alias_map = _collector_alias_map()
    unknown = [name for name in names if name not in alias_map]
    if unknown:
        raise ValueError("Unknown collector(s): {0}".format(", ".join(unknown)))

    normalized = []
    seen = set()
    for name in names:
        cli_name = alias_map[name]
        if cli_name in seen:
            continue
        normalized.append(cli_name)
        seen.add(cli_name)
    return normalized


def _default_enabled_collectors(config):
    selected = []
    for cli_name, alias_names, attr_names in COLLECTOR_SPECS:
        del alias_names
        for attr_name in attr_names:
            section = getattr(config, attr_name)
            if getattr(section, "enabled", False):
                selected.append(cli_name)
                break
    return selected


def resolve_enabled_collectors(config, only=None, exclude=None):
    """Resolve enabled collectors from config and CLI filters."""

    only_list = _normalize_collector_names(list(only or []))
    exclude_list = _normalize_collector_names(list(exclude or []))

    if only_list:
        selected = only_list
    else:
        selected = _default_enabled_collectors(config)
    if exclude_list:
        excluded = set(exclude_list)
        selected = [name for name in selected if name not in excluded]
    return selected


def install_signal_handlers(state):
    """Register SIGINT/SIGTERM handlers for graceful shutdown."""

    def _handle_signal(signum, frame):
        del frame
        state.request_shutdown(signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def _build_placeholder_payload(enabled_collectors):
    return {
        "mode": "placeholder",
        "collector_count": len(enabled_collectors),
        "enabled_collectors": enabled_collectors,
    }


def _close_collector(collector):
    close = getattr(collector, "close", None)
    if callable(close):
        close()


def _run_polling_collectors(collector_name, specs, state, interval_seconds, once, metric_key):
    collectors = []
    totals = []
    total_map = {}
    last_components = []
    iterations = 0

    try:
        for component_name, factory in list(specs or []):
            collector = factory()
            collectors.append((component_name, collector))
            total_map[component_name] = 0

        while not getattr(state, "shutdown_requested", False):
            iterations += 1
            last_components = []
            for component_name, collector in collectors:
                value = int(getattr(collector, "run_once")() or 0)
                total_map[component_name] += value
                last_components.append({"component": component_name, metric_key: value})
            if once:
                break
            if state.wait(interval_seconds):
                break

        for component_name, total in total_map.items():
            totals.append({"component": component_name, metric_key: total})

        return {
            "collector": collector_name,
            "mode": "once" if once else "poll",
            "iterations": iterations,
            "components": last_components,
            "totals": totals,
        }
    finally:
        for component_name, collector in collectors:
            del component_name
            _close_collector(collector)


def _run_polling_collectors_with_persistence(collector_name, specs, state, interval_seconds, once, metric_key, writer=None, batch_id=None):
    """Run polling collectors with optional database persistence.

    Args:
        collector_name: Name of the collector group
        specs: List of (component_name, factory) tuples
        state: RuntimeState for shutdown signaling
        interval_seconds: Polling interval
        once: If True, run only once
        metric_key: Key name for metrics
        writer: Optional TimescaleRawWriter for persistence
        batch_id: Optional batch ID for database writes

    Returns:
        Dict with collector results
    """
    collectors = []
    totals = []
    total_map = {}
    last_components = []
    iterations = 0

    try:
        for component_name, factory in list(specs or []):
            collector = factory()
            collectors.append((component_name, collector))
            total_map[component_name] = 0

        while not getattr(state, "shutdown_requested", False):
            iterations += 1
            last_components = []
            for component_name, collector in collectors:
                # Call run_once with batch_id and writer if supported
                run_once_method = getattr(collector, "run_once", None)
                if run_once_method is None:
                    value = 0
                else:
                    try:
                        # Try calling with batch_id and writer
                        value = int(run_once_method(batch_id=batch_id, writer=writer) or 0)
                    except TypeError:
                        # Fallback to no arguments
                        value = int(run_once_method() or 0)
                total_map[component_name] += value
                last_components.append({"component": component_name, metric_key: value})
            if once:
                break
            if state.wait(interval_seconds):
                break

        for component_name, total in total_map.items():
            totals.append({"component": component_name, metric_key: total})

        return {
            "collector": collector_name,
            "mode": "once" if once else "poll",
            "iterations": iterations,
            "components": last_components,
            "totals": totals,
        }
    finally:
        for component_name, collector in collectors:
            del component_name
            _close_collector(collector)


def _run_crypto_backfill(config):
    mode = getattr(config.runtime, "backfill_mode", "none")
    if mode == "none":
        return None

    kline_enabled = bool(getattr(config.crypto_kline, "enabled", False))
    metrics_enabled = bool(getattr(config.crypto_metrics, "enabled", False))
    if not kline_enabled and not metrics_enabled:
        return None

    from src.collectors.crypto import DataBackfiller
    from src.collectors.crypto.backfill import compute_lookback, get_backfill_config

    mode, days, start_date = get_backfill_config(config=config)
    lookback_days = compute_lookback(mode, days, start_date=start_date)
    if lookback_days <= 0:
        return None

    symbols = list(getattr(config.crypto_kline, "symbols", []) or []) or None
    provider = getattr(config.crypto_kline, "provider", "binance_futures_ws")
    backfiller = DataBackfiller(lookback_days=lookback_days, config=config)
    results = {}
    try:
        if kline_enabled:
            if provider == "gate_spot_poll":
                results["klines"] = {"status": "skipped", "reason": "unsupported_provider:gate_spot_poll"}
            else:
                results["klines"] = backfiller.run_klines(symbols=symbols)

        if metrics_enabled:
            results["metrics"] = backfiller.run_metrics(symbols=symbols)
    finally:
        _close_collector(backfiller)

    if not results:
        return None
    return {"component": "crypto_backfill", "result": results}


def _run_crypto_collectors(config, state=None, once=False):
    results = []
    runtime_state = state or RuntimeState()

    backfill_result = _run_crypto_backfill(config)
    if backfill_result is not None:
        results.append(backfill_result)

    if getattr(config.crypto_metrics, "enabled", False):
        from src.collectors.crypto import MetricsCollector

        collector = MetricsCollector(config=config)
        try:
            written = collector.run_once()
        finally:
            _close_collector(collector)
        results.append({"component": "crypto_metrics", "written": written})

    if getattr(config.crypto_kline, "enabled", False):
        from src.collectors.crypto import WSCollector

        collector = WSCollector(config=config)
        runtime_state.add_shutdown_hook(collector.stop)
        try:
            if once:
                results.append({"component": "crypto_kline", "status": "skipped", "reason": "once_mode"})
            else:
                collector.run()
                results.append({"component": "crypto_kline", "status": "completed"})
        finally:
            _close_collector(collector)

    if not results:
        return {"collector": "crypto", "status": "skipped", "reason": "disabled_by_config"}
    return {"collector": "crypto", "components": results}


def _run_orderbook_collectors(config, state=None, once=False):
    if not getattr(config.crypto_orderbook, "enabled", False):
        return {"collector": "orderbook", "status": "skipped", "reason": "disabled_by_config"}

    from src.collectors.crypto import OrderBookCollector

    collector = OrderBookCollector(config=config)
    runtime_state = state or RuntimeState()
    runtime_state.add_shutdown_hook(collector.stop)
    try:
        if once:
            return {"collector": "orderbook", "status": "skipped", "reason": "once_mode"}
        collector.run()
        return {"collector": "orderbook", "status": "completed"}
    finally:
        _close_collector(collector)


def _run_equity_collectors(config, state=None, once=False):
    if not getattr(config.equity, "enabled", False):
        return {"collector": "equity", "status": "skipped", "reason": "disabled_by_config"}

    from src.collectors.equity import CNEquityCollector, HKEquityCollector, USEquityCollector

    return _run_polling_collectors(
        collector_name="equity",
        specs=(
            ("us", lambda: USEquityCollector(config=config)),
            ("cn", lambda: CNEquityCollector(config=config)),
            ("hk", lambda: HKEquityCollector(config=config)),
        ),
        state=state or RuntimeState(),
        interval_seconds=getattr(config.equity, "poll_interval_seconds", 60),
        once=once,
        metric_key="written",
    )


def _run_news_collectors(config, state=None, once=False):
    if not getattr(config.news, "enabled", False):
        return {"collector": "news", "status": "skipped", "reason": "disabled_by_config"}

    from src.collectors.news import RssNewsCollector

    return _run_polling_collectors(
        collector_name="news",
        specs=(("rss", lambda: RssNewsCollector(config=config)),),
        state=state or RuntimeState(),
        interval_seconds=getattr(config.news, "poll_interval_seconds", 2),
        once=once,
        metric_key="inserted",
    )


def _run_fund_collectors(config, state=None, once=False):
    if not getattr(config.fund_cn, "enabled", False):
        return {"collector": "fund_cn", "status": "skipped", "reason": "disabled_by_config"}

    from src.collectors.fund import ETFFundCollector, OffMarketFundCollector
    from src.storage.raw_writer import TimescaleRawWriter

    # Create writer for persistence
    writer = None
    batch_id = None
    try:
        writer = TimescaleRawWriter()
        batch_id = writer.start_batch(market="fund_cn")
    except Exception as exc:
        sys.stderr.write("collector-service runtime: fund_cn writer init failed: {0}\n".format(exc))
        writer = None

    specs = []
    if list(getattr(config.fund_cn, "etf_symbols", []) or []):
        specs.append(("etf", lambda: ETFFundCollector(config=config, writer=writer)))
    if list(getattr(config.fund_cn, "offmarket_codes", []) or []):
        specs.append(("offmarket", lambda: OffMarketFundCollector(config=config, writer=writer)))
    if not specs:
        return {"collector": "fund_cn", "status": "skipped", "reason": "no_symbols_configured"}

    result = _run_polling_collectors_with_persistence(
        collector_name="fund_cn",
        specs=tuple(specs),
        state=state or RuntimeState(),
        interval_seconds=getattr(config.fund_cn, "interval_seconds", 60),
        once=once,
        metric_key="fetched",
        writer=writer,
        batch_id=batch_id,
    )
    result["persistence"] = "timescaledb"
    result["batch_id"] = batch_id
    return result


def _build_runtime_runners(config, state=None, once=False):
    return {
        "crypto": lambda: _run_crypto_collectors(config, state=state, once=once),
        "orderbook": lambda: _run_orderbook_collectors(config, state=state, once=once),
        "equity": lambda: _run_equity_collectors(config, state=state, once=once),
        "fund_cn": lambda: _run_fund_collectors(config, state=state, once=once),
        "news": lambda: _run_news_collectors(config, state=state, once=once),
    }


def _build_runtime_payload(enabled_collectors, runnable_collectors, unsupported_collectors, results, failed_collectors):
    return {
        "mode": "run",
        "collector_count": len(enabled_collectors),
        "enabled_collectors": list(enabled_collectors),
        "runnable_collectors": list(runnable_collectors),
        "unsupported_collectors": list(unsupported_collectors),
        "results": list(results),
        "failed_collectors": list(failed_collectors),
    }


def _execute_runtime_collectors(config, enabled_collectors, state=None, once=False):
    runners = _build_runtime_runners(config, state=state, once=once)
    runnable_collectors = [name for name in enabled_collectors if name in runners]
    unsupported_collectors = [name for name in enabled_collectors if name not in runners]
    results = []
    failed_collectors = []

    for name in unsupported_collectors:
        sys.stderr.write(
            "collector-service runtime: collector '{0}' has no runtime implementation yet.\n".format(name)
        )

    for name in runnable_collectors:
        try:
            outcome = runners[name]()
        except Exception as exc:
            failed_collectors.append(
                {
                    "collector": name,
                    "error": str(exc).strip() or exc.__class__.__name__,
                }
            )
            sys.stderr.write(
                "collector-service runtime: collector '{0}' failed: {1}\n".format(name, exc)
            )
            continue

        if isinstance(outcome, dict):
            results.append(outcome)
        else:
            results.append({"collector": name, "result": outcome})

    payload = _build_runtime_payload(
        enabled_collectors,
        runnable_collectors,
        unsupported_collectors,
        results,
        failed_collectors,
    )

    exit_code = 0
    if failed_collectors or unsupported_collectors:
        exit_code = 1
    return exit_code, payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector-service",
        description="collector-service: status payload by default, collectors run only with --run.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated collector selectors for this run: crypto,orderbook,equity,fund_cn,news.",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated collector selectors to remove: crypto,orderbook,equity,fund_cn,news.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the loaded config (redacted/safe) and exit.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute supported collectors instead of printing a dry-run status payload.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run supported collectors once and exit instead of entering polling/runtime loops.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.print_config:
        try:
            cfg = load_config()
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(cfg.to_public_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0

    try:
        cfg = load_config()
    except ValueError as exc:
        parser.error(str(exc))
    state = RuntimeState()
    install_signal_handlers(state)

    try:
        enabled_collectors = resolve_enabled_collectors(
            cfg,
            only=_split_collectors(args.only),
            exclude=_split_collectors(args.exclude),
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not args.run:
        print(
            json.dumps(
                _build_placeholder_payload(enabled_collectors),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        sys.stderr.write(
            "collector-service placeholder: collector execution is disabled by default. "
            "Use --run to execute supported collectors or --print-config to inspect config.\n"
        )
        return 0

    exit_code, payload = _execute_runtime_collectors(cfg, enabled_collectors, state=state, once=args.once)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
