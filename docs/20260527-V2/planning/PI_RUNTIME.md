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

> **基于 Pi 框架，接入本仓（tradeagnt）唯一版本的能力**，让 **Pi 具备交易场景的 Chat Agent 能力** —— 用户跟 Pi 聊；Pi 通过工具调用使用 tradeagnt 的行情、信号、评估、纸面与闭环，而不是在 Python 里再做一个聊天 Agent。

```text
  用户 ◄──chat──►  Pi（Chat Agent 外壳）
                      │
                      │ Extensions / Skills
                      ▼
              tradeagnt 能力层（Python 单体 v1 基建 + V2 硬闸门）
                      │
                      ├── tradecat_get_*（观察）
                      ├── 评估 / submit-thesis / audit（闭环）
                      └── 右栏 TUI 数据（KPI 快照）
```

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
| **`vendor/pi/`** | Pi 源码浅克隆（**gitignore**，换机见 `vendor/README.md`） |
| **`integrations/pi-extension/`** | tradeagnt 的 Pi Extension（v2-base 实现位） |
| `src/tradecat/` | Python 能力层（不变） |

## 待实现

- 左栏：嵌入式 `pi-tui` vs 旁路 `pi` CLI + IPC  

## 变更

- 2026-05-28：用户确认选用 Pi，非自研 Agent。
