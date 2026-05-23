# 新市场接入设计表（复制后填写）

> 填完后配合 [CHECKLIST.md](../CHECKLIST.md) 实施。

---

## 基本信息

| 项 | 填写 |
|:---|:---|
| 市场 ID（`market`） | 例：`hk_stock` |
| 中文名 | 例：港股 |
| 负责人 / 日期 | |
| 策略 demo 文件名 | 例：`hk_fast_5m.yaml` |

## 符号规范

| 项 | 填写 |
|:---|:---|
| canonical 示例 | 例：`00700` |
| 用户输入示例 | 例：`700`、`00700.HK` |
| 归一化规则 | |
| 是否与 crypto 冲突 | 是 / 否，如何区分 |

## 数据源

| 项 | 填写 |
|:---|:---|
| Provider 类名 | 例：`HkEquityProvider` |
| Provider `name` | 例：`hk_equity` |
| 主行情函数（tui/quote） | 例：`fetch_tencent_hk_quotes` |
| K 线 / 分钟线函数 | 例：`fetch_intraday_curve_1m(..., market=hk_stock)` |
| 支持 timeframe | 例：1m, 5m, 15m |
| 历史深度 | 例：当日 1m |
| 是否需要 API Key | |

## 策略

| 项 | 填写 |
|:---|:---|
| 默认 symbols | |
| 默认 timeframe | |
| 计价货币（展示） | 例：HKD |

## 测试计划

- [ ] `normalize_*` 单元测试
- [ ] Provider mock 测试
- [ ] `tradecat signal` smoke
- [ ] `tradecat backtest --mode scan` smoke
- [ ] `tradecat paper long` smoke
- [ ] crypto 回归

## 备注

（依赖、合规、交易时段、涨跌停等特殊逻辑）
