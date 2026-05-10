# 008-02 新骨架搭建

**Issue ID**: #008-02 | **Priority**: High | **Dependencies**: #008-01

## 目标
建立 `src/tradecat/` 统一包结构，作为后续所有模块的挂载点。

## 目录结构

```
src/tradecat/
├── __init__.py
├── __main__.py          # CLI入口: python -m tradecat
├── core/
│   ├── __init__.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py      # DataProvider ABC
│   │   ├── registry.py  # Provider注册表
│   │   ├── binance.py
│   │   └── gate.py
│   ├── indicators/
│   │   ├── __init__.py
│   │   └── base.py      # @indicator装饰器
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── engine.py    # SignalEngine
│   │   └── strategy.py  # YAML策略解析
│   └── paper_trading/
│       ├── __init__.py
│       ├── engine.py
│       ├── models.py
│       └── risk.py
├── data/
│   ├── __init__.py
│   ├── pg.py            # PG连接池
│   └── migrations/      # Alembic
├── cli/
│   ├── __init__.py
│   ├── main.py          # Click主命令
│   ├── quotes.py
│   ├── signals.py
│   ├── news.py
│   └── paper.py
├── tui/
│   ├── __init__.py
│   └── app.py
├── backtest/
│   ├── __init__.py
│   ├── runner.py
│   ├── walkforward.py
│   └── replay.py
└── config/
    └── strategies/      # YAML策略文件
```

## 任务清单

- [ ] 创建 `src/tradecat/` 完整目录树
- [ ] 编写根目录 `pyproject.toml`（Python 3.12, ruff, pytest）
- [ ] `src/tradecat/__main__.py` → `tradecat` CLI入口
- [ ] 迁移 `libs/common/` → `src/tradecat/common/`
- [ ] 编写 `core/providers/base.py`（DataProvider ABC）
- [ ] 编写 `core/indicators/base.py`（@indicator装饰器）
- [ ] `pip install -e .` 成功 + `tradecat --version` 输出

## 接口契约（供 003/004 Agent 参考）

**DataProvider 输出**:
```python
pd.DataFrame({"timestamp": [...], "open": [...], "high": [...], "low": [...], "close": [...], "volume": [...]})
```

**Indicator 函数签名**:
```python
@indicator(name="macd")
def compute_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ... # 返回包含新列的DataFrame，不写入数据库
```

**Signal 输出**:
```python
{"symbol": "BTCUSDT", "side": "LONG", "strength": 0.85, "timestamp": ...}
```

## 验收标准

- [ ] `pip install -e .` 成功
- [ ] `tradecat --version` 输出版本号
- [ ] `python -c "from tradecat.core.providers.base import DataProvider"` 无报错
- [ ] 旧 `services/` 目录仍可运行（不破坏现有功能）
