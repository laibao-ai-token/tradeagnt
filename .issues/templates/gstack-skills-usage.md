# Gstack Skills 使用说明（TradeCat）

## 1) 快速用法

1. 每一轮都显式点名 skill（不会自动跨轮继承）。
2. 可以组合多个 skill（按顺序执行）。
3. 先定目标，再选 skill，避免“为了用 skill 而用 skill”。

示例：

```text
用 plan-ceo-review 评审 007 范围和优先级。
用 guard，只允许改 services/signal-service/src。
用 qa-only 跑 4040 页面 smoke，只出报告不改代码。
```

---

## 2) 你当前最常用的 gstack skill（按落地流程）

### A. 方案与方向

| Skill | 作用 | 什么时候用 | 示例 |
|---|---|---|---|
| `office-hours` | 收敛问题定义和边界 | 需求还不清楚时 | `用 office-hours 收敛 007 的 7 天模拟盘目标` |
| `plan-ceo-review` | 产品/范围评审 | 判断先做什么、砍什么 | `用 plan-ceo-review 审 007` |
| `plan-design-review` | 设计方案评审（偏方案） | 有 UI/交互方案文档时 | `用 plan-design-review 看双 TUI 交互方案` |

### B. 开发安全与排障

| Skill | 作用 | 什么时候用 | 示例 |
|---|---|---|---|
| `guard` | `careful + freeze` 组合 | 需要安全+限定改动范围 | `用 guard，只改 scripts 和 services-preview/tui-service/src` |
| `careful` | 危险命令提醒 | 涉及高风险命令时 | `用 careful 模式执行接下来的操作` |
| `freeze` | 锁定可改目录 | 防止误改其他模块 | `用 freeze 限制到 services/signal-service/src` |
| `unfreeze` | 解除目录锁定 | 需要恢复全仓改动时 | `用 unfreeze` |
| `investigate` | 根因优先排障 | 线上/本地异常定位 | `用 investigate 查右侧 pane 无法输入` |

### C. 验证、发布、复盘

| Skill | 作用 | 什么时候用 | 示例 |
|---|---|---|---|
| `qa-only` | 只测试，不改代码 | 先拿客观测试报告时 | `用 qa-only 测 workbench 流程` |
| `ship` | 发布/提交流程化 | 准备合入或发布时 | `用 ship 流程处理当前改动` |
| `document-release` | 同步 README/AGENTS/文档 | 代码已改、文档需跟进 | `用 document-release 同步 007 文档` |
| `retro` | 迭代复盘 | 周期结束做总结 | `用 retro 复盘本周 003/006/007` |

### D. 浏览器相关

| Skill | 作用 | 什么时候用 | 示例 |
|---|---|---|---|
| `browse` | 无头浏览器操作/截图 | 需要网页验证、截图证据 | `用 browse 打开 4040 并截图` |
| `setup-browser-cookies` | 导入本机登录态 cookie | 需要访问登录后页面 | `先用 setup-browser-cookies，再用 browse 访问 Linear` |

### E. 设计类

| Skill | 作用 | 什么时候用 | 示例 |
|---|---|---|---|
| `design-consultation` | 产出设计系统 | 新页面/新产品起步时 | `用 design-consultation 产出资讯页设计规范` |
| `design-review` | 视觉/交互审查 | 页面已实现，需要打磨 | `用 design-review 审查视觉一致性` |

---

## 3) 推荐标准链路（只用 gstack）

### 功能推进（默认）

1. `office-hours`（可选）
2. `plan-ceo-review`
3. `guard`
4. 开发实现
5. `qa-only`
6. `document-release`
7. `ship`
8. `retro`（可选）

### 故障排查

1. `investigate`
2. 修复
3. `qa-only`
4. `ship`

---

## 4) 注意事项

- `qa-only` 不会自动修复问题，只给报告。
- `freeze/guard` 开启后，超出目录的改动会被限制。
- `plan-ceo-review` 是“方向与范围”，不是直接写代码。
- 浏览器类问题（Linear/登录态）优先 `setup-browser-cookies + browse`。

