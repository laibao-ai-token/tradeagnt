# TUI 第一刀减重：Agent Shell 抽离收口

> 最后更新: 2026-03-25
> 适用范围: `services-preview/tui-service` 中本地 placeholder Agent Shell 的独立模块化收口
> 当前状态: review
> 总体结论: 这块已经是最适合先拆的一刀，目标不是扩功能，而是把已开始的抽离动作收口，减少 `tui.py` 的边缘占位逻辑

---

## 目标

把 `tui.py` 里的本地 Agent Shell 占位子系统稳定抽到独立模块，并保证现有占位行为不变：

1. 不改真实业务能力
2. 不把新逻辑继续塞回 `tui.py`
3. 保持 `/new` `/model` `/tools` 本地 demo 行为与日志输出一致

## 写入边界

允许修改：

- `services-preview/tui-service/src/tui.py`
- `services-preview/tui-service/src/agent_shell.py`
- `services-preview/tui-service/tests/test_tui_agent_shell.py`
- `services-preview/tui-service/tests/conftest.py`
- 本 issue 文件

不要修改：

- `services-preview/tui-service/src/news_db.py`
- `services-preview/tui-service/tests/test_news_db.py`
- `services-preview/tui-service/tests/test_agent_events.py`
- 仓库根 README / AGENTS / 其他 issue

## 当前已知事实

- 当前工作区里已经存在未提交的 `agent_shell.py` 草稿与 `tui.py` 对接改动
- 现有抽离目标主要包含：
  - `AgentShellState / AgentShellMessage / AgentToolEvent`
  - 事件 JSONL 记录
  - `/new` `/model` `/tools` 输入处理
  - Agent 消息行渲染
- 已有验证基线：
  - `pytest -q tests/test_tui_agent_shell.py tests/test_agent_events.py`
  - `python3 -m py_compile services-preview/tui-service/src/agent_shell.py services-preview/tui-service/src/tui.py services-preview/tui-service/tests/conftest.py`

## 推荐执行步骤

1. 先核对当前 `agent_shell.py` 与 `tui.py` 的接线是否完整
2. 只保留 `tui.py` 中必要的 wrapper / curses 绘制入口，不再保留重复的状态与事件实现
3. 确保测试不再依赖整块 `src.tui` 的外部环境副作用
4. 运行最小测试与 `py_compile`
5. 把执行结果、残余风险回填到本文件

## 完成标准

- `agent_shell.py` 成为 Agent Shell 占位逻辑的唯一主实现
- `tui.py` 只保留调用与界面接线
- 相关测试通过
- 本文件更新“执行结果 / 风险 / 后续建议”

## 验证命令

```bash
cd services-preview/tui-service
pytest -q tests/test_tui_agent_shell.py tests/test_agent_events.py

cd /public/home/lixh6/laibao/proj/tx_test_0106/tradecat-origin
python3 -m py_compile \
  services-preview/tui-service/src/agent_shell.py \
  services-preview/tui-service/src/tui.py \
  services-preview/tui-service/tests/conftest.py
```

## 输出要求

完成后直接在本文件补：

- 实际修改文件
- 测试结果
- 还剩哪些 TUI 大块未拆
- 是否建议继续拆 `news` 或 `backtest`

## 执行结果

- 备注：
  - 当前工作区原先不存在描述里的本地 task 文件路径，本次先按 Linear 描述补齐了 `.issues/open/review/000-repo-review/007-tui-agent-shell-first-cut.md`，再在同文件回填执行结果。
- 实际修改文件：
  - `services-preview/tui-service/src/agent_shell.py`
  - `services-preview/tui-service/src/tui.py`
  - `services-preview/tui-service/tests/test_tui_agent_shell.py`
  - `services-preview/tui-service/tests/conftest.py`
  - `.issues/open/review/000-repo-review/007-tui-agent-shell-first-cut.md`
- 变更摘要：
  - 新增 `src/agent_shell.py`，集中承接 Agent Shell 状态 DTO、JSONL 事件写入、`/new` `/model` `/tools` 本地 demo 输入处理、消息换行渲染、滚动计算和右侧面板按键处理。
  - `src/tui.py` 改为只保留 workspace 布局、curses 绘制和主循环接线，删除重复的 Agent Shell 状态与事件实现。
  - `tests/test_tui_agent_shell.py` 改为直接覆盖 `src.agent_shell`，不再通过导入整块 `src.tui` 间接触发外部依赖。
  - 新增 `tests/conftest.py`，固定 `services-preview/tui-service` 为测试导入根，降低执行目录差异带来的副作用。
- 测试结果：
  - `cd services-preview/tui-service && pytest -q tests/test_tui_agent_shell.py tests/test_agent_events.py`
    - 结果：`13 passed in 0.25s`
  - `python3 -m py_compile services-preview/tui-service/src/agent_shell.py services-preview/tui-service/src/tui.py services-preview/tui-service/tests/conftest.py`
    - 结果：通过

## 残余风险

- `tui.py` 里仍保留 Agent Shell 的 curses 面板绘制和 workspace 级布局，这部分还依赖通用 UI 辅助函数，后续若继续拆 UI 组件需要再收一次边界。
- 本次没有接入真实 backend，只验证了本地 placeholder 行为保持不变。

## 还剩哪些 TUI 大块未拆

- `market_news` 相关的数据筛选、事件聚合、三栏绘制仍大量集中在 `tui.py`
- `market_backtest` 的产物读取、摘要格式化、图表绘制仍集中在 `tui.py`
- 多市场 quote/micro/master pane 的状态装配和渲染仍是大块内联逻辑

## 是否建议继续拆 `news` 或 `backtest`

- 建议优先继续拆 `news`
  - `news` 的数据准备、筛选状态、聚合和绘制耦合更重，拆开后能比 `backtest` 更明显地降低 `tui.py` 体积和测试成本
  - `backtest` 目前更偏只读看板，虽然也大，但业务变化面比 `news` 小，优先级可以排在后面
