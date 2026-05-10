from __future__ import annotations

from abc import ABC, abstractmethod

from tradecat.core.models.signal import AnalysisReport, Strategy
from tradecat.core.providers.base import DataProvider


class AnalysisPipeline(ABC):
    """分析流水线抽象基类."""

    def __init__(self, provider: DataProvider, strategy: Strategy) -> None:
        self.provider = provider
        self.strategy = strategy

    @abstractmethod
    async def run(self, symbol: str, timeframe: str) -> AnalysisReport:
        """执行分析流水线并返回 AnalysisReport."""
        ...
