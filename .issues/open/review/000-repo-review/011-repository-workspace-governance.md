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
> 总体结论: 当前最大的噪音来源之一不是源码本身，而是外挂仓、参考仓和本地联调目录持续混入主仓视野

## 目标

这张单的目标不是删目录，而是先形成治理名单：

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

- `find repository -maxdepth 2 -mindepth 1 -type d | sort` 返回 7 个路径：
  - `repository/OpenAlice`
  - `repository/codex`
  - `repository/iflow-cli`
  - `repository/longbridge-terminal`
  - `repository/nofx`
  - `repository/openclaw`
  - `repository/tradecat-upstream`
- `du -sh repository/* | sort -h` 当前均为 `4.0K`，说明工作区里只保留了空 checkout / gitlink 占位，不是完整外挂仓内容。
- 顶层额外压缩包 / 手工归档物：本次 `find . -maxdepth 2` 未发现 `zip/tar/tgz/7z`。

### Git 现状

- `git status --short` 当前为空，说明主仓视角下没有外挂仓脏状态直接冒出来。
- 但 `git ls-files -s repository` 显示这 7 个路径全部仍是 gitlink（mode `160000`），并没有真正从主仓索引里退出。
- `.gitmodules` 当前只登记了 `repository/openclaw`。
- `git submodule status` 直接失败：`fatal: no submodule mapping found in .gitmodules for path 'repository/OpenAlice'`。
- 结论：当前噪音不是“脏工作树”，而是“历史 gitlink 仍在索引里，但大部分已经脱离正式 submodule 管理”。

## Long-Term Keep

### `repository/openclaw`

- 这是当前唯一应长期保留的外挂仓路径。
- 依据：
  - `.gitmodules` 仍然只为它保留了正式映射。
  - `scripts/launch_trade_workbench.sh` 会显式检查 `repository/openclaw` 子模块状态。
  - `scripts/install_openclaw_tradecat_skill.sh`、`README.md`、`README_EN.md`、`AGENTS.md`、`docs/learn/openclaw_tradecat_skill_runbook.md` 都把它视为当前双 TUI / skill 联调路径的一部分。
- 治理口径：
  - 保留路径与 submodule 身份。
  - 不要求默认初始化。
  - 仅在 `openclaw` 联调、upstream 证据核验、workbench / skill / gateway 相关任务中显式纳入工作范围。

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

## Archive Candidates

### 第一优先级

#### `repository/codex`

- 未发现对 `repository/codex` 的仓库路径引用。
- 目录名与当前开发工具名高度重叠，最容易制造搜索与 review 语义噪音。

#### `repository/iflow-cli`

- 未发现任何当前脚本、README、文档或 issue 对该路径的直接依赖。
- 继续留在主工作区只会扩大“外挂仓在视野里”的误判成本。

#### `repository/longbridge-terminal`

- 未发现任何当前运行链路或文档依赖。
- 适合优先归档出主仓默认视野。

#### `repository/OpenAlice`

- 本次盘点未发现当前主线对该路径的直接引用。
- 它更像历史探索残留，不应继续占用主仓 review 注意力。

## Review Exclusion Rule

默认规则：

1. 主仓默认 review 范围不包含 `repository/*`。
2. 即使对象被保留，也不自动进入主仓 code review。
3. 只有当 ticket 明确点名某个外挂路径时，才把该路径临时纳入审查范围。

明确口径：

- `repository/openclaw`
  - 可长期保留，但默认仍排除在主仓 review 之外。
  - 只有涉及 `openclaw` workbench、skill、launcher、gateway 对账、upstream 证据核验时才显式纳入。
- `repository/nofx`、`repository/tradecat-upstream`
  - 视为参考仓，默认排除在主仓 review 之外。
- `repository/OpenAlice`、`repository/codex`、`repository/iflow-cli`、`repository/longbridge-terminal`
  - 在归档前也不应进入默认 review、默认搜索结果判断或“当前主线依赖”口径。

补充规则：

- 对 `repository/*` 的任何证据引用，必须先确认该路径已真正初始化并可读；空 gitlink 目录不能当作已验证源码证据。
- 对外挂仓的状态检查，不应再依赖全量 `git submodule status` 作为主仓日常巡检入口，因为当前历史 gitlink 与 `.gitmodules` 已不一致。

## Next Action

1. 先把主仓治理口径固定为：`repository/*` 默认不纳入 review。
2. 第一波归档建议按顺序处理：
   - `repository/codex`
   - `repository/iflow-cli`
   - `repository/longbridge-terminal`
   - `repository/OpenAlice`
3. 第二波再决策是否继续保留：
   - `repository/nofx`
   - `repository/tradecat-upstream`
4. `repository/openclaw` 保留，但应单独写明：
   - 它是“保留的上游依赖路径”，不是“主仓默认开发范围”。
5. 后续若要出清理执行手册，建议先补一条迁移动作：
   - 在执行归档前，为仍需保留语义的对象各写 1 段“为什么保留 / 为什么可归档”的摘要，避免路径移走后知识一并丢失。

## 完成标准对照

- [x] 形成可执行的外挂仓治理名单
- [x] 不做任何删除动作
- [x] 结论可直接回填到后续清理执行手册

## 执行记录

- 2026-03-25
  - 已盘点 `repository/*` 目录清单、当前 `git status`、体积信息、`.gitmodules` 与 gitlink 索引状态。
  - 已确认当前没有外挂仓脏工作树暴露在 `git status` 中。
  - 已确认真正的治理问题是：历史 gitlink 仍在主仓索引里，但除 `repository/openclaw` 外已无正式 submodule 映射。
  - 已形成 `Long-Term Keep` / `Reference Only` / `Archive Candidates` / `Review Exclusion Rule` / `Next Action`。
