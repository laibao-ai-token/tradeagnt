# tradeagnt 脱离上游检查清单

## 代码与 Git

- [x] `git remote` 仅 `laibao-ai-token/tradeagnt`
- [x] `tradeagnt` 分支已推送远端
- [ ] GitHub **Detach fork**（若页面仍显示 Forked from tradecat）
- [ ] GitHub 默认分支设为 **tradeagnt**（建议）
- [x] 根目录 README 指向本仓
- [x] `start.sh run` → 单体 TUI
- [x] CI 检查 `src/tradecat` + `freeze_verify`

## 文档与 Agent

- [x] 上游 README 归档
- [x] 微服务文档归档
- [x] `skills/tradeagnt/agents/manifest.json`（v1.0 只读工具表）
- [x] `docs/V1_AGENT_HARNESS.md`

## v1.0 封板后（非阻塞）

- [ ] `git push origin v1.0.0`
- [ ] v1.1：`agent_trade_thesis` + paper 闸门
- [ ] 全量 pytest 与 freeze 对齐
- [ ] `tui.py` 拆分（CLEANUP_ROADMAP）
