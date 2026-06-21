# FinceptTerminal 集成模块

## 概述

本模块封装了 FinceptTerminal 的 Python 分析功能，供 trade-agent 直接调用。

## 功能

### 1. 技术指标 (FinceptIndicators)

```python
from tradecat.fincept import FinceptIndicators

indicators = FinceptIndicators()

# 计算 RSI
rsi = indicators.rsi(close_prices)

# 计算 MACD
macd_line, signal_line, histogram = indicators.macd(close_prices)

# 综合分析
analysis = indicators.analyze(df)
```

**支持的指标:**
- SMA (简单移动平均)
- EMA (指数移动平均)
- RSI (相对强弱指数)
- MACD (指数平滑异同移动平均线)
- Bollinger Bands (布林带)
- ATR (平均真实波幅)
- Stochastic (随机指标)
- CCI (商品通道指数)
- Williams %R (威廉指标)

### 2. 回测模块 (FinceptBacktest)

```python
from tradecat.fincept import FinceptBacktest

backtest = FinceptBacktest()

# 查看可用策略
print(backtest.available_strategies)

# 运行回测
result = backtest.run(data, 'sma_crossover', {'fastPeriod': 10, 'slowPeriod': 30})

# 运行多个策略
results = backtest.run_multiple(data, ['sma_crossover', 'rsi', 'macd'])

# 找到最佳策略
best = backtest.find_best(data)
```

**支持的策略 (26个):**
- sma_crossover (SMA 均线交叉)
- ema_crossover (EMA 均线交叉)
- rsi (RSI 超买超卖)
- macd (MACD 趋势)
- bollinger_bands (布林带)
- momentum (动量策略)
- breakout (突破策略)
- ...

### 3. 新闻模块 (FinceptNews)

```python
from tradecat.fincept import FinceptNews

news = FinceptNews()

# 获取华尔街见闻
items = news.fetch_wallstreetcn(10)

# 获取同花顺快讯
items = news.fetch_tonghuashun(10)

# 获取新浪7x24
items = news.fetch_sina(10)

# 从所有数据源获取
items = news.fetch_all(5)

# 按关键词搜索
items = news.fetch_by_keyword("小米", 10)
```

**支持的数据源:**
- 华尔街见闻 (全球财经新闻)
- 同花顺 (A股快讯)
- 新浪7x24 (7x24小时资讯)

## 使用场景

### Agent 调用示例

```python
# 1. 获取股票数据
import requests
import json
import pandas as pd

url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
params = {"param": "sh688041,day,2026-01-01,2026-06-20,500,qfq"}
r = requests.get(url, params=params, timeout=10)
# ... 解析数据 ...

# 2. 技术分析
from tradecat.fincept import FinceptIndicators
indicators = FinceptIndicators()
analysis = indicators.analyze(df)

# 3. 策略回测
from tradecat.fincept import FinceptBacktest
backtest = FinceptBacktest()
best_strategy = backtest.find_best(df)

# 4. 获取新闻
from tradecat.fincept import FinceptNews
news = FinceptNews()
latest_news = news.fetch_all(10)
```

## 依赖

- pandas
- requests
- backtesting (回测模块)
- FinceptTerminal Python 脚本

## 路径

```
tradeagnt/src/tradecat/fincept/
├── __init__.py
├── indicators.py   # 技术指标
├── backtest.py     # 回测模块
├── news.py         # 新闻模块
└── README.md       # 本文档
```
