# 贡献指南

感谢关注 **tradeagnt**。本仓库为单体 `src/tradecat`，与上游 TradeCat 微服务版分离维护。

## 报告问题

请在本仓库提交 Issue：[github.com/laibao-ai-token/tradeagnt/issues](https://github.com/laibao-ai-token/tradeagnt/issues)

请尽量包含：现象、复现步骤、环境（OS、Python 版本）、相关日志片段。

## 提交 Pull Request

1. Fork [laibao-ai-token/tradeagnt](https://github.com/laibao-ai-token/tradeagnt)
2. 创建分支：`git checkout -b feat/your-feature`
3. 修改后运行：`./scripts/verify.sh` 与 `./scripts/freeze_verify.sh`（与改动相关时）
4. 推送并创建 PR

## 开发环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp config/.env.example config/.env
chmod 600 config/.env
```

启动 TUI：

```bash
TRADECAT_PIPELINE_PROFILE=tui_dual tradecat tui
```

## 代码规范

- Python 3.12+
- 格式化 / 检查：ruff（见 `pyproject.toml`）
- 勿提交 `config/.env`、本地 `data/*.db`、`libs/database/**/.paper_trading.consumer_state.json`

更多约束见根目录 [AGENTS.md](../AGENTS.md)。
