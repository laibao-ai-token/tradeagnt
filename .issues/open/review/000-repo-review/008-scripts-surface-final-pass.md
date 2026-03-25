# Scripts 表层收口最后一轮

> 最后更新: 2026-03-25
> 适用范围: 主仓 `scripts/` 顶层入口继续减重，形成稳定目录分层
> 当前状态: review
> 总体结论: 已完成一轮低风险表层收口，`scripts/` 根目录保留主入口与桥接命令，专项脚本已按 `analysis/backtest/data/quality` 下沉

---

## 目标

继续清理 `scripts/` 表层结构，但坚持低风险原则：

1. 不改业务语义
2. 不碰数据库 schema
3. 不做大规模删除
4. 优先做“位置整理 + 路径修复 + 文档同步”

## 写入边界

允许修改：

- `scripts/`
- `Makefile`
- `README.md`
- `README_EN.md`
- `AGENTS.md`
- 本 issue 文件

不要修改：

- `services/*/src/`
- `services-preview/*/src/`
- `.issues/open/review/000-repo-review/007-*.md` 之外的其他 repo-review issue
- `repository/*`

## 当前已知事实

* 本轮新增稳定分层：
  * `scripts/analysis/`
  * `scripts/backtest/`
  * `scripts/data/`
  * `scripts/quality/`
* 保留在根目录的脚本均为：
  * 主入口
  * 只读桥接命令
  * 或受外部引用约束、当前不宜继续移动的兼容入口

## 最终保留在 `scripts/` 根目录的脚本名单

### 主入口 / 桥接命令

* `scripts/backtest.sh`
* `scripts/backtest_issue_fill.py`
* `scripts/backtest_real_window_validation.sh`
* `scripts/check_env.sh`
* `scripts/init.sh`
* `scripts/install.sh`
* `scripts/install_openclaw_tradecat_skill.sh`
* `scripts/launch_trade_workbench.sh`
* `scripts/start.sh`
* `scripts/tradecat_get_backtest_summary.py`
* `scripts/tradecat_get_news.py`
* `scripts/tradecat_get_quotes.py`
* `scripts/tradecat_get_signals.py`
* `scripts/verify.sh`

### 暂留根目录

* `scripts/check_no_print_services.py`
  * 原因：CI 仍直接引用根路径；若继续移动，需要同时改 `.github/workflows/ci.yml`，超出本 ticket 写入边界。

## 新增下沉了哪些脚本

* `scripts/analysis/etf_backtest.py`
* `scripts/analysis/signal_correlation_analysis.py`
* `scripts/backtest/bt_indicator_db.sh`
* `scripts/data/download_hf_data.py`
* `scripts/data/export_timescaledb.sh`
* `scripts/data/export_timescaledb_main4.sh`
* `scripts/data/sync_market_data_to_rds.py`
* `scripts/data/timescaledb_compression.sh`
* `scripts/quality/check_async_sleep.py`
* `scripts/quality/check_i18n_keys.py`

## 文档同步范围

已同步：

* `Makefile`
* `README.md`
* `README_EN.md`
* `AGENTS.md`
* `scripts/verify.sh`
* 本 issue 文件

同步内容：

* `scripts/` 目录树
* 数据导入 / 导出 / 压缩命令路径
* 质量检查命令路径
* `export-db` 入口指向

## 剩余不建议继续移动的脚本及原因

* `scripts/backtest_real_window_validation.sh`
  * 已是回测 runbook 主入口，并被多份 backtest issue / README 明确引用。
* `scripts/backtest_issue_fill.py`
  * 与真实窗口校准闭环配套，属于用户直接执行的 issue 回填入口。
* `scripts/launch_trade_workbench.sh`
  * 属于用户直接执行的工作台入口，不是纯内部辅助脚本。
* `scripts/install_openclaw_tradecat_skill.sh`
  * 属于 bridge/runbook 安装入口，保留根路径更稳定。
* `scripts/check_no_print_services.py`
  * CI 已固定引用根路径；本 ticket 不改 workflow。

## 新旧路径扫描结果

### 已完成同步

以下活跃入口文件已不再引用旧路径：

* `README.md`
* `README_EN.md`
* `AGENTS.md`
* `Makefile`
* `scripts/verify.sh`

### 仍存在旧路径引用

扫描结果仍命中以下位置：

* `docs/ARCHITECTURE_ISSUES.md`
* `docs/analysis/architecture_refactoring_plan.md`
* `docs/analysis/module_health_analysis.md`
* `docs/analysis/signal_correlation.md`
* `.issues/open/001-feature-etf-auto-fund-selection.md`
* `.issues/open/review/007-review-e3f5f645-signal-rule-id-readonly-history.md`

保留原因：

* 上述文件属于历史分析文档 / 历史 issue 记录，不属于本 ticket 明确允许修改的主文档范围。
* 为保持低风险，本轮只同步主入口文档与当前 issue 文件，不扩散到历史审计材料。

## 验证记录

已执行：

```bash
find scripts -maxdepth 2 -type f | sort
bash -n scripts/*.sh scripts/backtest/*.sh scripts/data/*.sh
python3 -m py_compile scripts/analysis/*.py scripts/data/*.py scripts/quality/*.py scripts/backtest_issue_fill.py scripts/tradecat_get_*.py
python3 scripts/quality/check_async_sleep.py
python3 scripts/quality/check_i18n_keys.py
```

结果：

* shell 语法检查通过
* Python `py_compile` 通过
* `check_async_sleep.py` 通过
* `check_i18n_keys.py` 可执行，返回“未发现缺失键”

## 执行记录

* 2026-03-25：将专项脚本下沉到 `analysis/backtest/data/quality`
* 2026-03-25：修正移动后脚本的相对路径 / 导入 / 用法文案
* 2026-03-25：同步 `Makefile`、`README.md`、`README_EN.md`、`AGENTS.md`
* 2026-03-25：确认主入口与桥接命令仍稳定保留在 `scripts/` 根目录
