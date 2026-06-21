"""
FinceptTerminal 技术指标封装
提供 SMA、EMA、RSI、MACD、布林带等指标
"""

import sys
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd

# FinceptTerminal 路径
FINCEPT_PATH = Path(__file__).parent.parent.parent.parent.parent / "FinceptTerminal" / "fincept-qt" / "scripts" / "Analytics"


class FinceptIndicators:
    """FinceptTerminal 技术指标封装"""

    def __init__(self):
        self._ti = None
        self._init_indicators()

    def _init_indicators(self):
        """初始化技术指标模块"""
        try:
            if str(FINCEPT_PATH) not in sys.path:
                sys.path.insert(0, str(FINCEPT_PATH))
            from technical_indicators import TechnicalIndicators
            self._ti = TechnicalIndicators()
        except Exception as e:
            print(f"Warning: FinceptTerminal indicators not available: {e}")

    def sma(self, data: pd.Series, period: int = 20) -> Optional[pd.Series]:
        """简单移动平均线"""
        if self._ti is None:
            return None
        return self._ti.sma(data, period=period)

    def ema(self, data: pd.Series, period: int = 20) -> Optional[pd.Series]:
        """指数移动平均线"""
        if self._ti is None:
            return None
        return self._ti.ema(data, period=period)

    def rsi(self, data: pd.Series, period: int = 14) -> Optional[pd.Series]:
        """相对强弱指数"""
        if self._ti is None:
            return None
        return self._ti.rsi(data, period=period)

    def macd(self, data: pd.Series) -> Optional[Tuple[pd.Series, pd.Series, pd.Series]]:
        """MACD 指标"""
        if self._ti is None:
            return None
        return self._ti.macd(data)

    def bollinger_bands(self, data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Optional[Tuple[pd.Series, pd.Series, pd.Series]]:
        """布林带"""
        if self._ti is None:
            return None
        return self._ti.bollinger_bands(data, period=period, std_dev=std_dev)

    def atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[pd.Series]:
        """平均真实波幅"""
        if self._ti is None:
            return None
        return self._ti.atr(high, low, close, period=period)

    def stochastic(self, high: pd.Series, low: pd.Series, close: pd.Series) -> Optional[Tuple[pd.Series, pd.Series]]:
        """随机指标"""
        if self._ti is None:
            return None
        return self._ti.stochastic_oscillator(high, low, close)

    def cci(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> Optional[pd.Series]:
        """商品通道指数"""
        if self._ti is None:
            return None
        return self._ti.cci(high, low, close, period=period)

    def williams_r(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[pd.Series]:
        """威廉指标"""
        if self._ti is None:
            return None
        return self._ti.williams_r(high, low, close, period=period)

    def analyze(self, df: pd.DataFrame) -> dict:
        """综合分析"""
        if self._ti is None:
            return {"error": "FinceptTerminal not available"}

        close = df['Close']
        high = df['High']
        low = df['Low']

        # 计算所有指标
        sma5 = self.sma(close, 5)
        sma10 = self.sma(close, 10)
        sma20 = self.sma(close, 20)
        rsi = self.rsi(close)
        macd_line, signal_line, histogram = self.macd(close)
        upper, middle, lower = self.bollinger_bands(close)
        atr = self.atr(high, low, close)

        return {
            "sma": {
                "sma5": sma5.iloc[-1] if sma5 is not None else None,
                "sma10": sma10.iloc[-1] if sma10 is not None else None,
                "sma20": sma20.iloc[-1] if sma20 is not None else None,
            },
            "rsi": rsi.iloc[-1] if rsi is not None else None,
            "macd": {
                "macd_line": macd_line.iloc[-1] if macd_line is not None else None,
                "signal_line": signal_line.iloc[-1] if signal_line is not None else None,
                "histogram": histogram.iloc[-1] if histogram is not None else None,
            },
            "bollinger": {
                "upper": upper.iloc[-1] if upper is not None else None,
                "middle": middle.iloc[-1] if middle is not None else None,
                "lower": lower.iloc[-1] if lower is not None else None,
            },
            "atr": atr.iloc[-1] if atr is not None else None,
        }
