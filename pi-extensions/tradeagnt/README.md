# tradeagnt → Pi Extension

**目的**：让 **Pi 拥有垂类 Trade Agent 能力**（不是让 Pi 当配角）。

- Pi 源码：`../../vendor/pi/`
- Python 能力：`../../src/tradecat/`、`../../scripts/`

本地调试示例（路径以实现为准）：

```bash
cd ../../vendor/pi/packages/coding-agent
# pi --extension ../../../pi-extensions/tradeagnt/index.ts
```

v2-base：注册工具 `context_pack`、`get_quotes`、`get_signals` 等（调 repo 根下 Python 脚本）。
