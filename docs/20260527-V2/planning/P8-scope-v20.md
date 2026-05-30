# P8 — V2.0 范围

| 字段 | 值 |
|:---|:---|
| 状态 | 🟡 讨论中（Pi 已选型） |
| 总表 | [PLANNING.md](../PLANNING.md) § P8 |

## 要拍板什么

- M1～M4 哪些必须进 `v2.0.0` tag？
- 什么明确推迟到 V2.1？
- **Agent 框架（已选型）**：**[Pi](https://github.com/earendil-works/pi)**（`@earendil-works/pi-agent-core` + coding-agent / extensions），**不自研** Agent runtime。
- **嵌入方式（待拍）**：Pi **Extension/Skill** 调 Python `scripts/tradecat_get_*.py` 与 `tradecat agent *`；左栏 UI 可用 `pi-tui` 或 `pi-web-ui` 与右 Python TUI 同屏（实现细节 M1+）。

## 决策（拍板后填写）

- **V2.0 Must**：
- **V2.1 推迟**：
