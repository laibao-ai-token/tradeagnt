# 008-05 信号引擎改造

**Issue ID**: #008-05 | **Priority**: High | **Dependencies**: #008-03 + #008-04

## 目标
将 129 条硬编码规则迁移为 YAML 策略配置，信号写入 PG。

## 任务清单

### YAML 策略系统
- [ ] `config/strategies/crypto_scalp.yaml` — 加密货币超短线模板
- [ ] `config/strategies/default.yaml` — 默认保守模板
- [ ] YAML Schema 定义（signal_rules, thresholds, weights, cooldown）
- [ ] `core/signals/strategy.py` — YAML 解析器

### 信号引擎
- [ ] `core/signals/engine.py` — SignalEngine
  - 加载 YAML → 解析规则 → 评估权重 → 输出信号
  - 读取 `indicator_registry` 指标输出
  - 写入 `signal.history`
- [ ] 迁移 129 条规则中的高频核心规则（约 30-40 条）到 YAML
- [ ] 其余低频规则标记为 experimental（后续按需补充）

### 风控与输出
- [ ] 信号强度阈值过滤（仅输出 strength > threshold 的信号）
- [ ] 冷却机制：`signal.cooldown` 表替代 SQLite cooldown.db
- [ ] 信号写入 `signal.history`（PG），TUI 从 Queue/PG 读取

### 虚拟盘联动
- [ ] SignalEngine 输出 → PaperTradingEngine 消费（通过 Queue）

## 验收标准

- [ ] `tradecat signal --config crypto_scalp.yaml --symbol BTCUSDT` 输出信号 JSON
- [ ] `signal.history` 表中有记录
- [ ] 冷却生效：同一 symbol 在 cooldown 期内不重复触发
- [ ] 信号延迟 < 2 秒（从指标计算到信号输出）
