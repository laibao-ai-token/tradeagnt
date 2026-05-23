# DataProvider 实现规范

基类：`src/tradecat/core/providers/base.py`

## 接口契约

```python
class DataProvider(ABC):
    @property
    def name(self) -> str: ...          # 全局唯一，如 us_equity

    async def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> pd.DataFrame: ...              # 见下方 DataFrame 规范

    async def fetch_latest(self, symbol: str) -> dict[str, Any]: ...

    def supported_symbols(self) -> list[str]: ...

    def can_resolve(self, symbol: str) -> bool: ...

    async def close(self) -> None: ...   # 可选，释放连接
```

## DataFrame 规范

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `timestamp` | datetime64[ns, UTC] 或可解析时间 | 建议 UTC |
| `open` | float | |
| `high` | float | |
| `low` | float | |
| `close` | float | |
| `volume` | float | 无成交量可填 0 |

- 按时间 **升序**
- `SignalEngine` 用最后两行做 `prev` / `curr`；`scan_history` 遍历全表
- 若只有 1m 源，在 Provider 内 **resample** 到策略 `timeframe`（参考 `us_equity.py`）

## 注册

```python
# core/providers/registry.py → auto_register()
from tradecat.core.providers.xx_equity import XxEquityProvider
self.register(XxEquityProvider())
```

## 复用 TUI 行情

股票类市场优先：

1. 查 `tui/quote.py` 是否已有 `fetch_*_<market>*` / `fetch_intraday_curve_1m`
2. Provider 内 `asyncio.to_thread(...)` 包装同步 HTTP，避免阻塞事件循环
3. **不要**在 Provider 内复制 URL/解析逻辑

美股参考：`core/providers/us_equity.py` ← `fetch_nasdaq_us_minute_series` / `fetch_tencent_*`

## `can_resolve` 规则

- 与 `normalize_<market>_symbol` 一致：能归一化即返回 True
- 避免与 crypto 冲突（如纯字母 ticker 与 `USDT` 后缀区分）

## 能力边界（文档化）

在 Provider 类 docstring 写明：

- 支持哪些 `timeframe`
- 历史深度（如「仅当日 intraday ≤390 根 1m」）
- 是否需代理 / API Key

便于回测 CLI 设置合理 `--days`。

## 骨架文件

见 [templates/provider_skeleton.py](./templates/provider_skeleton.py)
