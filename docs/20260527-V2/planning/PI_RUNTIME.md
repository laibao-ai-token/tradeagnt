# Agent 运行时 — Pi 选型

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已选型（2026-05-28） |
| 关联 | P2 左栏 · P3 交互 · [CLOSED_LOOP.md](./CLOSED_LOOP.md) 编排 |

## 是什么

**[Pi](https://github.com/earendil-works/pi)**（earendil-works/pi，MIT）— 轻量 **Agent harness**，形态接近 **Claude Code / Codex**：

| 包 | 用途 |
|:---|:---|
| `pi-agent-core` | tool loop、状态 |
| `pi-coding-agent` | 交互 CLI（可裁剪） |
| `pi-ai` | 多模型 API |
| `pi-tui` / `pi-web-ui` | 终端/ Web UI 组件 |
| **Extensions / Skills** | 挂 **trade 工具**（我们的主扩展面） |

## 产品意图（用户原话对齐）

> 仓库仍是 **tradeagnt**（垂类产品 + 唯一版本 Python 能力）。  
> **拉 Pi 源码到 `vendor/pi/`**，在 **`pi-extensions/tradeagnt/`** 把能力 **接到 Pi 里面**，使 **Pi 具备 Trade Agent 垂类能力**。

```text
tradeagnt 仓库
  vendor/pi/                 ← Pi 框架（外壳）
  pi-extensions/tradeagnt/   ← 接入层（Extension）
  src/tradecat/ + scripts/   ← 已有能力（被 Extension 调用）
```

详见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 在 tradeagnt 里的分工

| 层 | 技术 | 做什么 |
|:---|:---|:---|
| **左栏 Agent** | **Pi** | 对话、多步调工具、步骤摘要 |
| **右栏看板** | **Python `tradecat` TUI** | 行情/KPI；TUI→Pi 快照 |
| **交易硬层** | **Python** | 评估、闸门、`PaperTradingEngine`、audit、scheduler |
| **工具** | Pi Extension → 调 `tradecat_get_*`、`tradecat agent submit-thesis` 等 | 观察 + 写入（经闸门） |

> **可持续性闭环**在 Python 硬层；Pi 负责 **编排与呈现**，不替代 fail-closed。

## 集成原则（V2）

1. **不 fork Pi 内核** — 用 Extensions/Skills 注册 trade 能力。  
2. **写模拟盘必须走 Python 闸门** — Pi 工具只递交 thesis JSON，由 `tradecat agent submit-thesis` 执行。  
3. **R3/R4 评估/调度** — Python 服务；Pi 可读 Feedback pack（短文本）。  
4. **TS + Python** — 首版用 **子进程调脚本**（与现有 `tradecat_get_*` 一致），避免双栈重写。

## 仓库内路径（2026-05-28）

| 路径 | 说明 |
|:---|:---|
| **`vendor/pi/`** | Pi 源码（gitignore） |
| **`pi-extensions/tradeagnt/`** | **能力接入 Pi**（v2-base 实现） |
| `src/tradecat/` | 垂类能力实现（Python，不变） |

## 待实现

- 左栏：嵌入式 `pi-tui` vs 旁路 `pi` CLI + IPC  

## 变更

- 2026-05-28：用户确认选用 Pi，非自研 Agent。
