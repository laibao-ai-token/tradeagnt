# Linear Issue 规范（TradeCat / TRA）

> **SSOT**：所有需求、Bug、迭代任务只在 Linear 创建；本地 `.issues/` 仅草稿，合并后删除或标注 `superseded-by: TRA-xx`。

## 1. 项目（Project）— 只认两个活跃入口

| 项目 | 状态 | 用途 |
|:---|:---|:---|
| **TradeCat v0.8** | Started | **唯一**新任务入口（当前开发） |
| **Archive: 008 monolith** | Completed | TRA-40～47 归档，只读 |
| **tradeagent** | Completed | 003/004/006/Review 历史，不再新增 |

## 2. 标签（必填 1 个 area + 1 个类型）

### area（模块，必选其一）

| 标签 | 适用 |
|:---|:---|
| `area:tui` | `src/tradecat/tui/`、三页、按键 |
| `area:paper` | 模拟盘、`core/paper_trading/` |
| `area:us-stock` | 美股 Provider、策略、`us_fast_5m.yaml` |
| `area:core` | signals/indicators/providers/CLI |
| `area:docs` | README、AGENTS、market-integration |
| `area:infra` | CI、MCP、脚本、Linear 本身 |

### 类型（必选其一）

`Feature` | `Bug` | `Improvement`

## 3. 标题格式

```
<area简写>: <动词> <对象>
```

示例：

- `tui: P2 模拟盘加密/美股子页隔离`
- `us-stock: NVDA 回测 scan 窗口校验`
- `core: paper SELL 平多回归测试`

## 4. 描述模板（复制到 Linear）

```markdown
## 背景
（为什么做，1～3 句）

## 验收标准
- [ ] 可验证条目 1
- [ ] 可验证条目 2

## 影响范围
- 路径：`src/tradecat/...`
- 配置：`config/strategies/...`（如有）
- 文档：README / AGENTS（如有）

## 验证命令
```bash
source .venv/bin/activate
pytest tests/test_xxx.py -q
tradecat ...
```

## 依赖 / 阻塞
- 阻塞：TRA-xx
- 相关：TRA-yy
```

## 5. 状态流转

```
Backlog → Todo → In Progress → In Review → Done
```

| 状态 | 何时 |
|:---|:---|
| Backlog | 已认可，未排期 |
| Todo | 本轮要做 |
| In Progress | 开发中（同时仅 1～2 条） |
| In Review | PR/自测完成待确认 |
| Done | 验收命令已跑通 |

## 6. Agent / 人工 开工检查清单

1. Linear 搜索是否已有重复 Issue
2. 必须挂在 **TradeCat v0.8**
3. 必须带 `area:*` + Feature/Bug/Improvement
4. 分支名建议：`TRA-54-short-desc`
5. 完成后评论写：改动文件 + 验证命令 + 是否更新文档

## 7. 禁止

- 不在 **tradeagent** 项目下新建 Issue
- 不在聊天里贴 API Key / `.env` 内容
- 不用「杂项」「TODO」等无 area 的标题
- 不一个 Issue 塞多个无关主题（应拆单）

## 8. 与 Git 的关系

完整流程见 **[git-linear-workflow.md](./git-linear-workflow.md)**。

- 分支：`TRA-54/tui-key-isolation`
- Commit：`feat(tui): ... (TRA-54)`
- PR 标题：`TRA-54: ...`，描述：`Closes TRA-54`

---

维护：结构变更时同步更新 `.cursor/rules/linear-workflow.mdc` 与 `AGENTS.md` §1.6。
