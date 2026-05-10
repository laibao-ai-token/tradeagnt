# 008-04 指标引擎迁移

**Issue ID**: #008-04 | **Priority**: High | **Dependencies**: #008-02 + #008-03

## 目标
从 `services/trading-service/src/indicators/` 迁移 **16 个核心指标**，删除 TV/Lean 实验指标。

## 保留的 16 个核心指标

| 旧文件 | 新位置 | 说明 |
|--------|--------|------|
| `incremental/macd.py` | `core/indicators/macd.py` | 核心 |
| `incremental/kdj.py` | `core/indicators/kdj.py` | 核心 |
| `incremental/atr.py` | `core/indicators/atr.py` | 核心 |
| `incremental/obv.py` | `core/indicators/obv.py` | 核心 |
| `incremental/cvd.py` | `core/indicators/cvd.py` | 核心 |
| `incremental/ema_gc.py` | `core/indicators/ema.py` | 简化为 EMA |
| `incremental/futures_sentiment.py` | `core/indicators/futures_sentiment.py` | 资金费率 |
| `incremental/buy_sell_ratio.py` | `core/indicators/buy_sell_ratio.py` | 买卖比 |
| `batch/bollinger.py` | `core/indicators/bollinger.py` | 核心 |
| `batch/vwap.py` | `core/indicators/vwap.py` | 核心 |
| `batch/vpvr.py` | `core/indicators/vpvr.py` | 核心 |
| `batch/super_trend.py` | `core/indicators/super_trend.py` | 核心 |
| `batch/support_resistance.py` | `core/indicators/support_resistance.py` | 核心 |
| `batch/k_pattern.py` | `core/indicators/k_pattern.py` | K线形态 |
| `batch/volume_ratio.py` | `core/indicators/volume_ratio.py` | 量比 |
| `safe_calc.py` | `core/indicators/rsi.py` | 从 safe_rsi() 提取 |

## 删除的指标（15个）

`data_monitor.py`, `futures_aggregate.py`, `futures_gap_monitor.py`, `harmonic.py`, 
`lean_indicators.py`, `liquidity.py`, `mfi.py`, `scalping.py`, `trend_line.py`,
`tv_big_money.py`, `tv_fib_sniper.py`, `tv_long_short.py`, `tv_rsi.py`,
`tv_trend_cloud.py`, `tv_volume_signal.py`, `tv_zero_lag.py`

## 注册机制

```python
from tradecat.core.indicators.base import indicator

@indicator(name="macd", category="momentum")
def compute_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ...
    return df  # 包含新列，不写入数据库
```

## 验收标准

- [ ] 16 个指标注册成功，`indicator_registry.list_all()` 返回 16 项
- [ ] `tradecat indicator macd BTCUSDT --timeframe 1h` 输出 DataFrame
- [ ] 指标输出与旧系统对比，差异 < 0.01%
- [ ] 无 `to_sql` / `read_sql` 调用
- [ ] TV/Lean 指标文件已删除
