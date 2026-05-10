# 008-01 废墟清理

**Issue ID**: #008-01 | **Priority**: High | **Dependencies**: 无

## 目标
删除废弃代码和仓库膨胀内容，缩小工作目录约 900M。

## 任务清单

- [ ] `git rm -rf _deprecated/` (137个文件)
- [ ] `git rm -rf docs/analysis/` (14个文件)
- [ ] `git rm -rf repository/` 子模块 (3个文件)
- [ ] `git rm pyproject.toml` (根目录)
- [ ] `rm -rf services/*/.venv/` (清理虚拟环境)
- [ ] `rm -rf services/*/data/* services/*/logs/*`
- [ ] `git ls-files | wc -l` < **900**（删除前 1047）
- [ ] `du -sh .` < 500M（删除前 1.3GB）
- [ ] `grep -r "telegram" "bot"` 确认无残留推送代码
- [ ] `git commit -m "chore: remove deprecated code and submodules"`

## 备注
- 保留 `.issues/` 和 `skills/`
- 不删除 `services/` 目录本身（后续逐步迁移代码）
