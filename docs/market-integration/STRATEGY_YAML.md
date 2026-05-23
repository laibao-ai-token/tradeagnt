# 策略 YAML 约定

路径：`config/strategies/`（加载逻辑见 `StrategyLoader`）

## 必填字段

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `name` | string | 策略显示名 |
| `market` | string | **市场枚举**（见下表） |
| `symbols` | list[string] | 标的列表（写用户友好形式，加载时归一化） |
| `timeframe` | string | K 线周期：`1m` `5m` `15m` `1h` `1d` 等 |
| `indicators` | list | 指标名 + `params` |
| `rules` | list | 声明式规则 |
| `thresholds` | map | 如 `min_strength`、`max_cooldown` |

## `market` 枚举（扩展时登记）

| 值 | 含义 | 状态 |
|:---|:---|:---:|
| `crypto` | 加密货币现货/合约对（`BASE_QUOTE`） | 已用 |
| `us_stock` | 美股 ticker | 已用 |
| `hk_stock` | 港股 | 待接 |
| `cn_stock` | A 股 | 待接 |
| `cn_fund` | 场内/场外基金 | 待接 |

新增市场时：**先在本表登记**，再改代码。

## 规则 `condition.type`

与 crypto 共用，见 `core/signals/models.py` → `ConditionType`：

- `threshold_cross_up` / `threshold_cross_down`
- `cross_up` / `cross_down`
- `state_change`
- `contains`
- `range_enter` / `range_exit`
- `custom`（遗留桥接，新市场勿依赖）

## 示例：美股

```yaml
name: "US Paper RSI 5m"
market: us_stock
symbols:
  - NVDA
  - META
timeframe: 5m
indicators:
  - name: rsi
    params:
      period: 14
rules:
  - name: RSI超卖反弹买入
    direction: BUY
    strength: 62
    cooldown: 300
    condition:
      type: threshold_cross_up
      field: rsi
      threshold: 35
    message_template: "RSI超卖反弹: {rsi:.1f}"
    fields:
      rsi: rsi
thresholds:
  min_strength: 50
  max_cooldown: 600
```

## 版本发布

```bash
# 修改 current/<file>.yaml 后
python3 scripts/strategy_release.py snapshot -n "说明" --activate
python3 scripts/strategy_release.py list
```

环境变量：

- `TUI_SIGNAL_STRATEGY=current/us_fast_5m.yaml` — TUI 后台 poller 使用策略
