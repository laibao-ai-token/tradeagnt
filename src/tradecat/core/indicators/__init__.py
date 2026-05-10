from tradecat.core.indicators.base import IndicatorMeta, IndicatorRegistry, indicator

__all__ = ["indicator", "IndicatorRegistry", "IndicatorMeta", "auto_register"]


def auto_register() -> None:
    """Import all indicator modules to trigger @indicator decorators."""
    from tradecat.core.indicators import (
        macd, kdj, atr, obv, cvd, ema, rsi,
        futures_sentiment, buy_sell_ratio, bollinger,
        vwap, vpvr, super_trend, support_resistance,
        k_pattern, volume_ratio,
    )
