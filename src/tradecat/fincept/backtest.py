"""
FinceptTerminal 回测模块封装
提供策略回测功能
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd

# FinceptTerminal 路径
FINCEPT_PATH = Path(__file__).parent.parent.parent.parent.parent / "FinceptTerminal" / "fincept-qt" / "scripts" / "Analytics" / "backtesting" / "backtestingpy"


class BacktestResult:
    """回测结果"""
    def __init__(self, result: dict):
        self.result = result

    @property
    def return_pct(self) -> float:
        return self.result.get('Return [%]', 0)

    @property
    def max_drawdown(self) -> float:
        return self.result.get('Max. Drawdown [%]', 0)

    @property
    def sharpe_ratio(self) -> float:
        return self.result.get('Sharpe Ratio', 0)

    @property
    def trades(self) -> int:
        return self.result.get('# Trades', 0)

    @property
    def win_rate(self) -> float:
        return self.result.get('Win Rate [%]', 0)

    def to_dict(self) -> dict:
        return {
            "return_pct": self.return_pct,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "trades": self.trades,
            "win_rate": self.win_rate,
        }


class FinceptBacktest:
    """FinceptTerminal 回测模块封装"""

    def __init__(self):
        self._strategies = {}
        self._init_strategies()

    def _init_strategies(self):
        """初始化回测策略"""
        try:
            if str(FINCEPT_PATH) not in sys.path:
                sys.path.insert(0, str(FINCEPT_PATH))
            from btp_strategies import STRATEGY_BUILDERS
            self._strategies = STRATEGY_BUILDERS
        except Exception as e:
            print(f"Warning: FinceptTerminal backtest not available: {e}")

    @property
    def available_strategies(self) -> List[str]:
        """可用策略列表"""
        return list(self._strategies.keys())

    def run(self, data: pd.DataFrame, strategy_name: str, params: dict = None, cash: float = 100000) -> Optional[BacktestResult]:
        """运行回测"""
        if strategy_name not in self._strategies:
            print(f"Strategy {strategy_name} not found")
            return None

        try:
            from backtesting import Backtest

            builder = self._strategies[strategy_name]
            Strategy = builder(params or {})
            bt = Backtest(data, Strategy, cash=cash, commission=.002)
            result = bt.run()

            return BacktestResult(result)
        except Exception as e:
            print(f"Backtest failed: {e}")
            return None

    def run_multiple(self, data: pd.DataFrame, strategies: List[str] = None, cash: float = 100000) -> Dict[str, BacktestResult]:
        """运行多个策略回测"""
        if strategies is None:
            strategies = list(self._strategies.keys())[:10]

        results = {}
        for name in strategies:
            result = self.run(data, name, cash=cash)
            if result:
                results[name] = result

        return results

    def find_best(self, data: pd.DataFrame, strategies: List[str] = None, cash: float = 100000) -> Optional[str]:
        """找到最佳策略"""
        results = self.run_multiple(data, strategies, cash)

        if not results:
            return None

        best_name = max(results.keys(), key=lambda x: results[x].sharpe_ratio)
        return best_name
