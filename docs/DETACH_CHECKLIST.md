# tradeagnt 脱离上游检查清单

## 代码与 Git

- [x] `git remote` 仅 `laibao-ai-token/tradeagnt`
- [ ] `git push origin tradecat`（需本机凭据）
- [ ] GitHub **Detach fork**（若页面仍显示 Forked from tradecat）
- [x] 根目录 README 指向本仓
- [x] `start.sh run` → 单体 TUI
- [x] CI 检查 `src/tradecat` + `freeze_verify`

## 文档

- [x] 上游 README 归档至 `docs/archive/`
- [x] 微服务文档归档至 `docs/archive/microservices-era/`
- [x] `docs/README.md` 索引

## 数据与配置

- [x] `data/` 路径双轨 + 迁移脚本
- [x] `config/.env.standalone.example`
- [ ] 生产 `config/.env` 改用 standalone 模板（本地操作）

## 可选后续（v1.0）

- [ ] 全量 pytest 与 freeze 对齐
- [ ] `tui.py` / `quote.py` 拆分（见 CLEANUP_ROADMAP）
- [ ] 包名 `tradecat` → `tradeagnt`（大改，非必须）
