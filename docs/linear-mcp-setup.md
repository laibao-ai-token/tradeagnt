# Linear MCP 配置（Cursor / TradeCat）

> 后续需求与任务跟踪统一走 **Linear**；Agent 通过 MCP 读写 Issue，不再只靠口头描述。

## 1. 仓库内已包含的配置

| 文件 | 说明 |
|:---|:---|
| [`.cursor/mcp.json`](../.cursor/mcp.json) | 项目级 MCP（已启用 Linear 官方远程端点） |
| [`.cursor/mcp.json.example`](../.cursor/mcp.json.example) | 含 API Key 备选方案的示例 |
| [`.cursor/rules/linear-workflow.mdc`](../.cursor/rules/linear-workflow.mdc) | Agent 使用 Linear 的流程规则 |

## 2. 在 Cursor 中启用（必做）

1. 确认本机有 **Node.js 18+** 与 **npx**（`node -v`、`npx -y` 可用）。
2. 打开 **Cursor Settings → Features → MCP**（或 **Tools & MCP**）。
3. 找到 **linear**，打开开关；若未出现，点 **Refresh** 或重启 Cursor。
4. 首次连接 **Linear 官方远程 MCP** 时按提示完成 **OAuth 登录**（推荐，无需把 Key 写进仓库）。
5. 在 Agent 对话里应能看到 Linear 相关 tools（创建/查询/更新 Issue 等）。

官方文档：<https://linear.app/docs/mcp>

## 3. 备选：API Key（stdio）

若 OAuth 不可用，在 Linear → **Settings → API → Personal API keys** 创建 Key，写入本机环境（**不要提交**）：

```bash
# 写入 config/.env（已 gitignore）或 shell profile
export LINEAR_API_KEY=lin_api_xxxx
```

将 `.cursor/mcp.json` 改为 `.cursor/mcp.json.example` 中的 `linear-api` 块，或合并进 `mcpServers`。

`config/.env.example` 中已预留 `LINEAR_API_KEY` 占位，供 `envFile` 或手动 export 使用。

## 4. Agent 工作流约定

1. **开工前**：在 Linear 查是否已有对应 Issue；没有则创建（标题含模块，如 `tui` / `paper` / `us_stock`）。
2. **开发中**：大任务拆 Sub-issue；PR/分支名带 Issue ID（如 `TC-123`）。
3. **完成后**：Issue 标 Done，备注验证命令（如 `tradecat tui`、`pytest tests/test_us_equity.py`）。
4. **本地 `.issues/`**：可作草稿与架构备忘；**以 Linear 为单一事实来源（SSOT）**。

## 5. 故障排查

| 现象 | 处理 |
|:---|:---|
| MCP 列表无 linear | 确认项目根存在 `.cursor/mcp.json`；重启 Cursor |
| `npx` 超时 | 配置代理或预装 `npm i -g mcp-remote` |
| OAuth 失败 | 改用 API Key + `linear-api` 配置 |
| tools 不可用 | Settings 中确认 linear 已 Enable；Agent 模式需允许 MCP |

## 6. 与 TradeCat 仓库的关系

- MCP **不替代** `tradecat` CLI / TUI，只管理**任务与需求**。
- 代码改动仍在 `src/tradecat/`；市场接入见 `docs/market-integration/`。
- Agent 手册见根目录 [`AGENTS.md`](../AGENTS.md) 第 1.6 节。
