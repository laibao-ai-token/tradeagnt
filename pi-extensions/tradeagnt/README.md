# tradeagnt → Pi Extension（E2）

实现进度见：`pi/docs/trade-agent/execution/E2-TOOLS.md`

## E2 工具（目标）

| 工具 | 脚本 |
|:---|:---|
| `trade_get_quotes` | `scripts/tradecat_get_quotes.py` |
| `trade_get_indicators` | `scripts/tradecat_get_indicators.py` |
| `trade_get_news` | `scripts/tradecat_get_news.py` |

## 本地调试

```bash
export TRADEAGNT_ROOT=/path/to/tradeagnt
cd ../pi
pi -e "$TRADEAGNT_ROOT/pi-extensions/tradeagnt/index.ts" \
  --provider xiaomi-token-plan-sgp --model mimo-v2.5-pro
```

`run-trade-agent.sh` 在存在 `index.ts` 时自动 `-e` 本扩展。
