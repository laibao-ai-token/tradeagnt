# P7 — 安全与 fail-closed

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已锁定（2026-05-28，全部采用默认） |
| 总表 | [PLANNING.md](../PLANNING.md) § P7 |

## 决策（已锁定）

**不新增特别配置项**；沿用 P5 + 行业默认：

| 项 | 默认 |
|:---|:---|
| 缺 leverage/notional/exit 等 | **fail-closed 拒绝** |
| thesis 与本地信号反向 | **warn**（不额外做可配置 reject UI） |
| 美股非 RTH | **允许纸面**（模拟），limitations 可写在 thesis |
| 实盘/密钥/签名 | **禁止**（P1） |
| 环境 | 仅 `TRADEAGNT_AGENT_MODE` / `EXEC_MODE` 等 P6 已有开关，**不加** P7 专用 env 墙 |

> 若后续要收紧，走 **迭代小版本** 改规则，不扩 P7 配置面。
