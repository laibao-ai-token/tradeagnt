from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class IndicatorMeta:
    """指标元数据."""

    name: str
    category: str
    inputs: list[str]
    func: Callable[..., Any]
    params: dict[str, Any] = field(default_factory=dict)


class IndicatorRegistry:
    """指标注册表（单例）."""

    _instance: IndicatorRegistry | None = None
    _indicators: dict[str, IndicatorMeta]

    def __new__(cls) -> IndicatorRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._indicators = {}
        return cls._instance

    def register(
        self,
        *,
        name: str,
        category: str,
        inputs: list[str],
        func: Callable[..., Any],
        params: dict[str, Any] | None = None,
    ) -> None:
        """注册一个指标函数."""
        if name in self._indicators:
            raise ValueError(f"Indicator '{name}' is already registered.")
        self._indicators[name] = IndicatorMeta(
            name=name,
            category=category,
            inputs=inputs,
            func=func,
            params=params or {},
        )

    def get(self, name: str) -> IndicatorMeta:
        """获取已注册指标的元数据."""
        if name not in self._indicators:
            raise KeyError(f"Indicator '{name}' not found.")
        return self._indicators[name]

    def list_indicators(self) -> list[IndicatorMeta]:
        """返回所有已注册指标列表."""
        return list(self._indicators.values())


def indicator(
    *,
    name: str,
    category: str = "general",
    inputs: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """指标函数注册装饰器.

    示例::
        @indicator(name="macd", category="momentum", inputs=["close"])
        def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
            return df
    """
    inputs = inputs or []

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _registry = IndicatorRegistry()
        _registry.register(
            name=name,
            category=category,
            inputs=inputs,
            func=func,
        )
        func._indicator_meta = {  # type: ignore[attr-defined]
            "name": name,
            "category": category,
            "inputs": inputs,
        }
        return func

    return decorator
