# vendor/

第三方源码，**不提交**到 tradeagnt 主仓（见根 `.gitignore`）。

## Pi Agent 框架

```bash
# 首次 / 换机后（在仓库根目录）
git clone --depth 1 https://github.com/earendil-works/pi.git vendor/pi
```

| 路径 | 说明 |
|:---|:---|
| `vendor/pi/` | [earendil-works/pi](https://github.com/earendil-works/pi) 浅克隆 |
| `integrations/pi-extension/` | tradeagnt 侧 Extension（调 Python `tradecat_get_*`，v2-base 待建） |

tradeagnt 仍为 **唯一开发目录**；Pi 为左栏 harness，交易能力仍在 `src/tradecat/`。
