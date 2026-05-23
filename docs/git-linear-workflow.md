# Git × Linear 提交流程（TradeCat v0.8）

> **原则**：Linear 管「做什么」；Git 管「改了什么」。一条 Linear Issue 对应 **一个分支 + 一小串语义化 commit**，合并后 Issue 标 Done。

---

## 1. 日常循环（固定 6 步）

```text
Linear Backlog/Todo
    → 建分支 TRA-xx/简短英文
    → 开发 + 小步 commit（每条带 TRA-xx）
    → push + PR（标题含 TRA-xx）
    → 验收（pytest / tradecat …）
    → Linear Done + 合并 PR
```

| 步骤 | 谁 | 动作 |
|:---|:---|:---|
| 1 | 人/Agent | Linear 建或认领 Issue（**TradeCat v0.8** + `area:*`） |
| 2 | 开发 | `git checkout -b TRA-58/tui-key-isolation` |
| 3 | 开发 | 改代码，**按逻辑拆 commit**（见 §3） |
| 4 | 开发 | `git push -u origin HEAD` |
| 5 | Review | 开 PR：`TRA-58: tui 按键隔离` |
| 6 | 合并后 | Linear → Done；必要时写验证命令 |

**禁止**：一个巨大 commit 混 TUI + 美股 + 文档 + Linear 配置且无 Issue 号。

---

## 2. 分支命名

```text
TRA-<编号>/<英文关键词>
```

示例：

- `TRA-59/us-stock-dual-poller`
- `TRA-52/tui-p1-visual`
- `TRA-60/docs-linear-spec`

`tradecat` 主分支保持可发布；功能在分支上做完再 merge。

---

## 3. Commit Message 格式

```text
<type>(<scope>): <中文或英文简述> (TRA-xx)
```

| type | 用途 |
|:---|:---|
| `feat` | 新功能 |
| `fix` | Bug |
| `docs` | 仅文档 |
| `refactor` | 行为不变的重构 |
| `test` | 测试 |
| `chore` | 构建/脚本/配置模板 |

| scope | 示例 |
|:---|:---|
| `tui` | 终端 |
| `paper` | 模拟盘 |
| `us-stock` | 美股 |
| `core` | signals/providers |
| `cli` | tradecat 命令 |
| `infra` | MCP/verify/AGENTS |

**示例**

```text
feat(us-stock): add UsEquityProvider and symbol normalize (TRA-45)
feat(tui): P1/P2 sub-tabs and key isolation (TRA-58)
docs(infra): align AGENTS.md with monolith layout (TRA-60)
```

---

## 4. PR 规范

- **标题**：`TRA-xx: 与 Linear Issue 标题一致或更短`
- **描述**：
  - `Closes TRA-xx` 或 `Related TRA-xx`
  - 验收清单（从 Linear 复制）
  - 验证命令
- **粒度**：一个 PR 尽量 **只做一个 Issue**；超大 Issue 拆子 Issue

---

## 5. 当前未提交改动 — 建议拆分（参考 2026-05）

工作区约 **26 修改 + 46 未跟踪**。建议 **分 5～6 个 PR** 合入，不要一次 squash 全扔：

| 顺序 | PR / Issue | 包含路径（示意） | 说明 |
|:---|:---|:---|:---|
| 1 | TRA-60 或新 `infra` | `docs/linear-*`, `docs/git-linear-workflow.md`, `docs/pipeline/`, `.cursor/rules/`, `.cursor/mcp.json.example`, `config/.env.example`, `config/pipeline/`, `AGENTS.md`, `scripts/verify.sh` | 规范与 MCP，无业务逻辑 |
| 2 | 008 归档 / `core` | `src/tradecat/core/symbols/`, `us_equity.py`, `providers/registry`, `cli/*` market 透传, `config/strategies/us_fast_5m.yaml`, `tests/test_us_equity.py` | 美股能力 |
| 3 | `paper` | `core/paper_trading/*`（ledger/metrics/consolidate）, `tui/pages/paper.py`, `cli/paper.py` | 模拟盘 |
| 4 | `tui` | `src/tradecat/tui/**`（除已并入 paper 的） | TUI 三页/按键/双 poller |
| 5 | `docs` | `docs/market-integration/**`, `config/strategies/README.md` | 接入文档 |
| 6 | 可选 `chore` | `scripts/strategy_release.py`, `news_sync_*`, `config/strategies/releases/` | 工具脚本，可单独或跟 docs |

### 不要提交

| 路径 | 原因 |
|:---|:---|
| `config/.env` | 含密钥 |
| `libs/database/**/.paper_trading.consumer_state.json` | 运行时状态 |
| `skills/Untitled` | 无效草稿 |
| `.venv/` | 本地环境 |

`.cursor/mcp.json` 无 Key 可提交；密钥只在 `config/.env`。

---

## 6. 推荐命令模板（整理当前树）

```bash
# 0) 确认在 tradecat 分支且干净理解
git status -sb

# 1) 文档/infra 第一条 PR
git checkout -b TRA-60/infra-linear-docs
git add AGENTS.md config/.env.example docs/linear-*.md docs/git-linear-workflow.md \
  docs/pipeline/ config/pipeline/ .cursor/rules/ .cursor/mcp.json.example scripts/verify.sh
git commit -m "$(cat <<'EOF'
docs(infra): Linear MCP, pipeline spec, and AGENTS monolith alignment (TRA-60)

EOF
)"
git push -u origin HEAD

# 2) 美股 — 新建分支自 tradecat，cherry-pick 或按路径 add
# … 依此类推
```

若已混在一起改完，可用 **`git add -p`** 按 hunk 拆 commit，或 `git stash` + 分分支恢复。

---

## 7. 与 Agent 协作

- 开工 prompt：「实现 TRA-58，分支 `TRA-58/tui-key-isolation`，commit 带 TRA-58」
- 禁止 Agent 在未要求时 `git push`
- 合并前：`./scripts/verify.sh` + 相关 `pytest`

---

## 8. 相关文档

- Issue 怎么写：[linear-issue-spec.md](./linear-issue-spec.md)
- Pipeline 固化：[pipeline/README.md](./pipeline/README.md)
