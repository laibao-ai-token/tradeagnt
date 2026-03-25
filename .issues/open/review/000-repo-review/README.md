# 仓库级 Review 总览

- 目录：`.issues/open/review/000-repo-review`
- 目标：沉淀“提交级 review”之外的仓库级审计、治理基线和架构对齐记录
- 使用方式：
  - 提交级 review 继续放在 `.issues/open/review/` 根目录
  - 仓库级审计、卫生治理、架构映射放在本子目录

## 当前文档

| ID | 文档 | 状态 | 说明 |
|---|---|---|---|
| 001 | `001-architecture-audit.md` | draft | 主仓边界、服务边界、review 推进顺序 |
| 002 | `002-repository-hygiene-audit.md` | draft | 冗余目录、运行产物、数据资产保护、Git 噪音 |
| 003 | `003-007-target-architecture-mapping.md` | draft | `#007` 目标能力与当前主仓模块的建议落位映射 |
| 004 | `004-service-review-sequence.md` | draft | 按桥接层、信号层、展示层、上游服务拆分整仓 review 顺序 |
| 005 | `005-cleanup-playbook.md` | draft | 固定清理顺序、禁止触碰项、清理前后验证方式 |
| 006 | `006-architecture-boundary-decisions.md` | draft | 把 `scripts` / `signal-service` / `tui-service` / 外部编排层的职责边界正式冻结 |
| 007 | `007-tui-agent-shell-first-cut.md` | review | 已回填 SYM 执行结果，TUI 第一刀减重已完成收口记录 |
| 008 | `008-scripts-surface-final-pass.md` | review | 已回填 SYM 执行结果，`scripts/` 根目录收口结论已固定 |
| 009 | `009-signal-service-domain-readiness-review.md` | review | 已回填 SYM 审查结论，明确 `signal-service` 只宜承接信号域 |
| 010 | `010-trading-service-backfill-and-core-review.md` | review | 已回填 SYM 审查结论，下一刀应优先减重 `backfill_indicators.py` |
| 011 | `011-repository-workspace-governance.md` | review | 已回填并执行首轮清理，主仓索引只保留 `OpenAlice` / `nofx` / `tradecat-upstream` |
| 012 | `012-mainline-switch-to-openalice.md` | decision | 已定稿：`OpenAlice` 为新主仓，`TradeCat` 封板，`openclaw.backup` 仅作参考 |

## 当前阶段结论

- `001-006` 已经覆盖仓库级 review 的最小基线：
  - 仓库边界
  - 卫生审计
  - `#007` 落位映射
  - 服务级 review 顺序
  - 清理执行手册
  - 架构硬边界定稿
- `007-011` 已在 SYM 并行执行并完成回填：
  - `007`：Agent Shell 第一刀已收口，后续优先继续拆 `news`
  - `008`：`scripts/` 表层分层已固定，主入口与桥接命令边界已明确
  - `009`：`signal-service` 适合作为 signal intent / rule evaluation 层，不宜直接长成完整交易主域
  - `010`：`trading-service` 当前最大维护热点是 `backfill_indicators.py`
  - `011`：`repository/*` 已形成治理口径并完成首轮清理，旧仓默认不再 review 外挂仓
- `012` 已正式冻结主仓切换口径：
  - `repository/OpenAlice` = 新主线主仓
  - `tradecat-origin` = 封板旧仓 / 能力来源仓
  - `repository/openclaw.backup-20260324T161300Z` = 运行时参考仓
- 下一步不建议继续补框架文档
- 下一步应从“TradeCat 能力迁移清单”开始，围绕 `OpenAlice` 推进新主线
