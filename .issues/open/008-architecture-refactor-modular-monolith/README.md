# 008 架构重构：模块化单体

**Status**: Open  
**Priority**: P0  
**决策汇总**:

| # | 决策 | 选择 |
|---|------|------|
| 1 | 市场优先级 | A: 先加密货币，美股/基金 Phase 2 |
| 2 | 核心指标 | 保留16个，删除 TV/Lean 实验指标 |
| 3 | 回测模式 | 全部5种保留 |
| 4 | Telegram Bot | 完全删除 |
| 5 | 数据库 | 统一 TimescaleDB，删除 SQLite |
| 6 | 指标预计算 | 先实时计算，后续按需优化 |
| 7 | 架构 | 模块化单体（1进程 + 1DB） |

---

## 迁移阶段

| 阶段 | Issue | 内容 | 依赖 |
|------|-------|------|------|
| M0 | #008-01 | 清理废弃代码 | - |
| M1 | #008-02 | 搭建新骨架 | M0 |
| M2 | #008-03 | Provider + 数据层 | M1 |
| M3a | #008-04 | 指标引擎 | M2 |
| M3b | #008-05 | 信号引擎 | M3a+04 |
| M4 | #008-06 | TUI + CLI | M3b |
| M5 | #008-07 | 回测 + Docker + CI | M4 |
| - | #008-08 | 虚拟盘引擎 | M3b |

## 新架构

```
tradecat (统一进程)
├── CLI / TUI
├── Provider 插件层 (Binance/Gate/...)
├── Data Layer (PG/TimescaleDB)
├── Indicator Engine (@indicator)
├── Signal Engine (YAML策略)
├── Paper Trading Engine
└── Backtest Engine
```

## 收益预估

- 代码量: -65~70%
- 启动时间: 分钟→秒
- 虚拟盘精度: float→Decimal（零误差）
- 扩展性: 新交易所 = 1个Provider文件
