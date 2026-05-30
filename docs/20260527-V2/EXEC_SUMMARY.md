# V2 执行摘要（决策者只看这一页）

> 最后更新：2026-05-28 · 分支：`v2/agent-harness`  
> 协作：[CONTROL_PLANE.md](../CONTROL_PLANE.md) · 规划总表：[PLANNING.md](./PLANNING.md)

---

## 一句话

**V2 = vendor/pi（Pi 外壳）+ pi-extensions/tradeagnt（能力接入 Pi）+ Python 闭环**；见 [ARCHITECTURE.md](./ARCHITECTURE.md)。先 v2-base，再迭代。

---

## 规划进度

| 块 | 状态 |
|:---|:---:|
| P1～P6、P7、P8、P9 | ✅ |
| Pi 选型 | ✅ |
| **CLOSED_LOOP**（L1～L4） | 🟡 可选再拍；不挡 v2-base 开工 |

---

## 已锁定要点（极简）

| 主题 | 结论 |
|:---|:---|
| 定位 | Trade-layer Claude Code；非实盘 |
| 界面 | 左 **Pi** / 右 **TUI**；人引导 40/60 |
| 数据 | 现有 `tradecat_get_*`、signal_history |
| 写入 | **R2+R3+R4 都要**；可切换；R3/R4 先评估再 submit |
| v1 共存 | 一套 TUI；V2 关 auto_consumer 抢写 |
| 安全 P7 | **全默认**，不加特别配置 |
| 发版 P8 | **迭代**；当前目标 **v2-base** → 再 v2.0.1（R3）… |
| 验收 P9 | **每小版本一段 AC**；v2-base 绿了就打 tag |

---

## v2-base 要交付什么（当前工程目标）

1. Pi Extension 能调研究工具（至少 `context_pack`）。  
2. **R2**：submit-thesis + audit + paper-report。  
3. 右 TUI 可跑；`TRADEAGNT_AGENT_MODE` 互斥。  
4. **不含**（放到下一迭代）：R3 调度、R4、24h 自动循环、完整双栏嵌入 polish。

---

## 唯一可选规划尾项

[CLOSED_LOOP.md](./planning/CLOSED_LOOP.md) 的 **L1～L4**（R3 触发器、收手规则）— 可边做 v2-base 边定。

---

## 下一步（实现）

**开始 v2-base 工程**：Pi Extension 骨架 + `tradecat agent submit-thesis` + audit.jsonl。

回 **`开工 v2-base`** 我从 M1/M2a 任务列表开干（仍 CEO 摘要汇报）。
