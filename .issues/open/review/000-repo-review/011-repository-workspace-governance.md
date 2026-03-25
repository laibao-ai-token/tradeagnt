---
title: "011-repository-workspace-governance"
status: review
created: 2026-03-25
updated: 2026-03-25
owner: codex
priority: medium
type: review
linear: TRA-39
---

# 外挂仓与工作区治理名单

> 最后更新: 2026-03-25
> 适用范围: `repository/*` 与其他外挂工作区在主仓中的治理口径
> 当前状态: review
> 总体结论: 第一轮清理已经完成，`tradecat-origin` 主仓索引中的外挂 gitlink 只保留 `OpenAlice` / `nofx` / `tradecat-upstream`，其余对象改按“本地参考目录”治理，不再混入主仓默认 review

## 目标

这张单的目标是先形成治理名单，再把第一轮低风险清理真正落地：

1. 哪些外挂仓长期保留
2. 哪些只是参考仓
3. 哪些适合归档出主工作区视野
4. 哪些必须明确“不纳入主仓默认 review 范围”

## 写入边界

只允许修改：

- 本 issue 文件

不要修改：

- `repository/*` 中任何文件
- `.gitignore`
- 任何业务代码与 README

## 盘点快照

### 当前对象

- 当前本地工作区中，`find repository -maxdepth 1 -mindepth 1 -type d | sort` 返回 12 个目录：
  - `repository/chatgpt_register_v2_by_AI`
  - `repository/CLIProxyAPI`
  - `repository/ESPRIT`
  - `repository/gstack`
  - `repository/longbridge-terminal`
  - `repository/nofx`
  - `repository/OpenAlice`
  - `repository/openclaw.backup-20260324T161300Z`
  - `repository/opencli`
  - `repository/symphony`
  - `repository/tradecat-upstream`
  - `repository/worldmonitor`
- 这些目录里，只有 `repository/OpenAlice`、`repository/nofx`、`repository/tradecat-upstream` 仍然留在主仓索引里；其余已经不是主仓受管对象。
- `repository/openclaw.backup-20260324T161300Z` 属于运行时参考仓，本地保留即可，不再作为主仓 gitlink 管理。

### Git 现状

- `git status --short` 当前为空，说明主仓视角下没有外挂仓脏状态直接冒出来。
- `git ls-files -s repository` 当前只剩 3 个 gitlink（mode `160000`）：
  - `repository/OpenAlice`
  - `repository/nofx`
  - `repository/tradecat-upstream`
- `.gitmodules` 已删除，不再使用正式 submodule 映射管理 `repository/*`。
- 第一轮清理已完成：
  - 已删除历史 `repository/openclaw` gitlink，并清理掉陈旧 `.gitmodules` 映射
  - 已从主仓索引移除 `repository/codex`
  - 已从主仓索引移除 `repository/iflow-cli`
  - 已从主仓索引移除 `repository/longbridge-terminal`
  - 已把 `repository/OpenAlice` 和 `repository/tradecat-upstream` 指针前移到当前参考版本
- 结论：当前噪音不再来自“历史 gitlink 大面积残留”，而主要来自本地工作区里还保留着若干未纳入主仓治理的参考目录。

## Retained In Index

### `repository/OpenAlice`

- 这是当前唯一需要在治理文档中明确标成“主线锚点”的外挂仓路径。
- 依据：
  - `012-mainline-switch-to-openalice.md` 已正式冻结“新主线主仓 = `repository/OpenAlice`”。
  - 当前主仓仍保留它的 gitlink，用于把 `tradecat-origin` 与新主线建立可见锚点。
- 治理口径：
  - 可以保留在主仓索引里。
  - 默认仍排除在 `tradecat-origin` 的 code review / repo review / 全仓搜索范围之外。
  - 只有在“迁移到新主线”或“同步新主线锚点”这类任务里才显式点名。

## Reference Only

### `repository/nofx`

- 当前仅适合视为历史参考对象，不属于主线开发依赖。
- 依据：
  - 仓库内仍能看到 `nofx-dev` 的历史架构描述（如 `docs/learn/base.md`、`docs/analysis/architecture_analysis_report.md`）。
  - 但没有发现任何当前脚本、README 或运行路径直接依赖 `repository/nofx`。
- 治理口径：
  - 若保留，只作为历史方案对照或路线回顾材料。
  - 默认排除在主仓 review、测试和日常搜索范围之外。

### `repository/tradecat-upstream`

- 当前更像手工保留的上游基线占位，适合作为参考仓，而不是默认工作区对象。
- 依据：
  - 名称上仍有“上游基线”价值。
  - 但本次没有发现任何脚本、README、运行链路对该路径的直接引用。
- 治理口径：
  - 若短期保留，只允许在“对照上游差异”这类明确任务中显式使用。
  - 不纳入默认 code review / repo review / 工作区巡检。

### `repository/openclaw.backup-20260324T161300Z`

- 当前更适合作为运行时 / 交互能力参考仓，而不是旧主仓的一部分。
- 依据：
  - `012-mainline-switch-to-openalice.md` 已把它定义为“运行时参考仓”。
  - 它不应再通过主仓索引来表达依赖关系。
- 治理口径：
  - 本地保留即可。
  - 默认不纳入主仓 review，也不作为主仓 tracked object 管理。

## Archived From Index

以下对象已完成第一轮归档，不再保留为主仓 gitlink：

#### `repository/codex`

- 未发现对 `repository/codex` 的仓库路径引用。
- 目录名与当前开发工具名高度重叠，最容易制造搜索与 review 语义噪音。
- 当前状态：
  - 已从主仓索引移除。
  - 若本地仍保留目录，只按本地参考目录处理。

#### `repository/iflow-cli`

- 未发现任何当前脚本、README、文档或 issue 对该路径的直接依赖。
- 继续留在主工作区只会扩大“外挂仓在视野里”的误判成本。
- 当前状态：
  - 已从主仓索引移除。
  - 若本地仍保留目录，只按本地参考目录处理。

#### `repository/longbridge-terminal`

- 未发现任何当前运行链路或文档依赖。
- 适合优先归档出主仓默认视野。
- 当前状态：
  - 已从主仓索引移除。
  - 本地目录可继续保留真实 WIP，但不再拖脏主仓。

#### `repository/openclaw`

- 旧双 TUI / skill 路线已从主仓主流程移除。
- 当前状态：
  - 已从主仓索引移除。
  - 已清理陈旧 `.gitmodules` 映射。

## Review Exclusion Rule

默认规则：

1. 主仓默认 review 范围不包含 `repository/*`。
2. 即使对象被保留，也不自动进入主仓 code review。
3. 只有当 ticket 明确点名某个外挂路径时，才把该路径临时纳入审查范围。

明确口径：

- `repository/OpenAlice`
  - 作为新主线锚点保留。
  - 默认仍排除在旧仓 review 之外。
- `repository/nofx`、`repository/tradecat-upstream`
  - 视为参考仓，默认排除在主仓 review 之外。
- `repository/codex`、`repository/iflow-cli`、`repository/longbridge-terminal`、`repository/openclaw`
  - 已退出主仓索引，不应再作为主仓依赖对象讨论。
- 其他本地目录（如 `repository/symphony`、`repository/gstack`、`repository/opencli` 等）
  - 仅按本地参考工作区处理，不纳入主仓默认审查范围。

补充规则：

- 对 `repository/*` 的任何证据引用，必须先确认该路径已真正存在且源码可读；本地空目录、备份目录和未初始化对象不能当作已验证源码证据。
- 对外挂仓状态检查，不再使用 `git submodule status` 作为主仓巡检入口，因为 `tradecat-origin` 已不再以 `.gitmodules` 管理这批对象。

## Next Action

1. 先把主仓治理口径固定为：`repository/*` 默认不纳入 review。
2. 第一轮低风险归档已完成，无需继续在旧仓里追清 `codex` / `iflow-cli` / `longbridge-terminal` / `openclaw`。
3. 后续若还要减噪，优先处理“本地目录是否搬出仓库根目录”，而不是继续改主仓索引。
4. `repository/OpenAlice` 仅保留“主线锚点”语义，不代表旧仓继续依赖它开发。
5. 真实开发主线继续按 `012` 冻结结论执行：新能力推进去 `repository/OpenAlice`，旧仓只做封板维护和迁移参考。

## 完成标准对照

- [x] 形成可执行的外挂仓治理名单
- [x] 完成第一轮低风险 gitlink 清理
- [x] 让主仓 `git status` 回到干净状态
- [x] 结论可直接回填到后续清理执行手册

## 执行记录

- 2026-03-25
  - 已盘点当前本地 `repository/` 目录清单与主仓索引中的 gitlink 清单。
  - 已执行第一轮清理提交：
    - `fc622bc8` `chore(repo): drop stale openclaw submodule mapping`
    - `965230c7` `chore(repo): remove archived codex and iflow-cli gitlinks`
    - `8cc08cb7` `chore(repo): bump OpenAlice gitlink`
    - `6b200489` `chore(repo): bump tradecat-upstream gitlink`
    - `8a9c41f4` `chore(repo): archive longbridge-terminal gitlink`
  - 已确认主仓索引里只剩 `OpenAlice` / `nofx` / `tradecat-upstream` 三个 gitlink。
  - 已确认当前主仓 `git status --short` 为空。
