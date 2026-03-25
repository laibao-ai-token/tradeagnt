# Trading Service 大文件与核心分层审查

> 最后更新: 2026-03-25
> 适用范围: `services/trading-service` 的大文件与 `core/` 分层是否足够清晰
> 当前状态: review
> 总体结论: `trading-service` 不是当前主线第一优先级，但它的超大脚本和 `core` 分层会直接影响后续整仓可维护性

---

## 目标

这张单也是 review-only，不要求改代码。  
重点是确认：

1. `core/io` / `core/compute` / `core/storage` 分层是否真落地
2. `backfill_indicators.py` 为什么还这么大
3. 后续如果要减重，最值得先拆哪一块

## 写入边界

只允许修改：

- 本 issue 文件

不要修改：

- 任何业务代码
- 任何 README / AGENTS / 其他 issue

## 重点核查文件

- `services/trading-service/src/core/io.py`
- `services/trading-service/src/core/compute.py`
- `services/trading-service/src/core/storage.py`
- `services/trading-service/src/core/engine.py`
- `services/trading-service/src/scripts/backfill_indicators.py`

## 需要回答的问题

1. `core/` 三层的边界现在是否真实存在
2. `backfill_indicators.py` 的大块职责分别是什么
3. 哪些职责可以安全拆出去
4. 哪些地方虽然大，但暂时不值得动
5. 如果做第一刀减重，建议拆成哪些模块

## 输出格式要求

请在本文件中补充：

1. `Findings`
2. `Large File Breakdown`
3. `First-Cut Split Proposal`
4. `Risks`

`Findings` 至少 3 条，按严重度排序。

## 建议命令

```bash
wc -l services/trading-service/src/scripts/backfill_indicators.py
rg -n "class |def " services/trading-service/src/scripts/backfill_indicators.py
rg -n "class |def " services/trading-service/src/core/*.py
```

## 完成标准

- 本文件能直接指导下一轮 `trading-service` 减重
- 明确“先拆什么 / 先别拆什么”
- 不做代码改动

## 执行记录

* 2026-03-25：当前工作区缺少 Linear 描述中给定的本地 issue 文件路径；按该描述补建到 `.issues/open/review/000-repo-review/010-trading-service-backfill-and-core-review.md`，避免审查结果散落到其他 review 文件。
* 2026-03-25：人工审查 `services/trading-service/src/core/io.py`、`services/trading-service/src/core/compute.py`、`services/trading-service/src/core/storage.py`、`services/trading-service/src/core/engine.py`、`services/trading-service/src/scripts/backfill_indicators.py`。
* 2026-03-25：确认文件体量：`backfill_indicators.py` 为 `1397` 行；`core/io.py` `62` 行，`core/compute.py` `213` 行，`core/storage.py` `116` 行，`core/engine.py` `193` 行。

## Findings

1. `High`：`core/io -> core/compute -> core/storage` 这条三层边界只在 `Engine.run()` 主路径里真实存在，但并没有成为 `trading-service` 的统一执行边界。
   - 证据：
     - `services/trading-service/src/core/engine.py:55-57` 的确把主计算流程委托给 `.io`、`.compute`、`.storage`。
     - 但 `services/trading-service/src/scripts/backfill_indicators.py:38-46` 直接导入 `reader`、`writer`、指标注册表和 `src.core.async_full_engine.get_high_priority_symbols_fast`。
     - `services/trading-service/src/scripts/backfill_indicators.py:1099-1233` 又单独实现了 slow/fast 两套读取、计算、去重、写入流程，完全绕开 `core/`。
   - 结论：`core/` 更像“实时主引擎的一条整理过的 happy path”，而不是服务级架构边界；后续任何关于缓存、写入后处理、错误处理的变更，都需要在 backfill 脚本里再维护一套。

2. `Medium`：`storage.py` 的边界不纯，已经混入跨库读取和后处理副作用，严格意义上不再是“只写层”。
   - 证据：
     - `services/trading-service/src/core/storage.py:14-39` 的 `write_results()` 在批量写 SQLite 后，还会无条件调用 `update_market_share()` 和 `cleanup_futures_1m()`。
     - `services/trading-service/src/core/storage.py:50-99` 的 `update_market_share()` 先读 PostgreSQL 聚合结果，再回写 SQLite。
   - 影响：`storage` 现在同时承担“落盘、跨库聚合、清理修正”三类职责；这会让调用方很难只复用“写入”而不触发后处理，也让后续测试与拆分边界变得模糊。

3. `Medium`：`io.py` 和 `engine.run_single()` 说明 `core/` 分层存在明显漏口，当前更偏“代码整理”而非“硬边界”。
   - 证据：
     - `services/trading-service/src/core/io.py:23-28` 的 `load_klines()` 不只是读数据，还在决定是否初始化缓存、并主动刷新 interval cache。
     - `services/trading-service/src/core/io.py:42-62` 的 `preload_futures_cache()` 直接根据指标名做条件预取，属于带业务知识的数据准备。
     - `services/trading-service/src/core/engine.py:175-193` 的 `run_single()` 直接拿 cache、直接 `indicator.compute()`、直接写库，没有走 `.io` / `.compute`。
   - 结论：三层不是假的，但还不是“所有入口都必须经过”的边界；它对主批量引擎成立，对单指标路径和 backfill 路径不成立。

4. `Low`：`backfill_indicators.py` 之所以还大，不是因为 CLI 或参数解析，而是因为它把“快路径指标实现”本身也收进了脚本文件。
   - 证据：
     - `services/trading-service/src/scripts/backfill_indicators.py:84-993` 基本都是 `_backfill_*_fast` 的向量化历史回填实现。
     - `services/trading-service/src/scripts/backfill_indicators.py:996-1020` 还有一整块 `FAST_BACKFILLERS` 注册表把这些实现绑在脚本里。
   - 判断：大头是“纯计算内核”，不是 argparse；因此第一刀不该先去拆 CLI，而该先把这些纯函数搬离脚本。

## Large File Breakdown

`services/trading-service/src/scripts/backfill_indicators.py` 当前大致可以分成 7 块：

1. 启动与环境引导：`18-83`
   - `_bootstrap_src_package()`、环境开关、SQLite readiness probe。
   - 体量不大，但说明这个脚本仍然在自己解决包加载和表 readiness，而不是复用统一入口。

2. 通用 DataFrame/Series 辅助函数：`146-175`、`420-439`、`559-567`
   - `_to_float_series()`、`_to_int_series()`、`_build_base_frame()`、`_trend_bias_series()`、`_wilder_smooth()`。
   - 这些是纯 helper，和 CLI/DB 没耦合，安全可拆。

3. 向量化 fast backfill 指标实现：`84-993`
   - 含 `基础数据同步器.py`、`MACD柱状扫描器.py`、`布林带扫描器.py`、`SuperTrend.py`、`Ichimoku.py`、`VWAP离线信号扫描.py`、`智能RSI扫描器.py`、`K线形态扫描器.py` 等。
   - 这是全文件最大的职责块，也是造成脚本接近 1400 行的主要原因。
   - 大部分函数形态都是 `DataFrame -> DataFrame` 的纯计算，拆分风险相对最低。

4. Fast backfiller 注册与通用 fallback：`996-1043`
   - `FAST_BACKFILLERS` 和 `_broadcast_last_row()`。
   - 这是 fast 回填和普通指标实例之间的桥接层，应与第 3 块一起迁出。

5. 参数/计划构建：`1045-1098`
   - `_normalize_list()`、`_parse_int_overrides()`、`_build_bar_limit_map()`。
   - 这是 CLI 规划逻辑，不大，但和指标内核没有直接关系。

6. 单 symbol/interval 执行器：`1099-1233`
   - `backfill_symbol_interval()`：slow path，滚动窗口逐步调用 `indicator.compute()`。
   - `backfill_symbol_interval_fast()`：fast path，直接调用 fast backfiller 或 broadcast fallback，并批量写入。
   - 这一块混合了读库、计算选择、去重、裁剪 retention、写库，是 orchestration 核心。

7. 全量 traversal 与 CLI：`1236-1397`
   - `backfill_all()` + `argparse`。
   - 这块是脚本入口控制层，虽然也不短，但不是文件变大的主要根因。

哪些职责可以安全拆出去：

* 最安全：第 2、3、4 块。因为它们基本都是纯函数或纯注册表，迁出后行为边界最清楚。
* 次安全：第 5 块。它只管参数和 bar limit 规划，拆出去不会碰业务计算。
* 相对谨慎：第 6 块。它已经碰到 `reader` / `writer` / retention / 去重策略，拆分前要先明确和 `core` 的关系。

哪些地方虽然大，但暂时不值得动：

* `services/trading-service/src/core/engine.py`
  - 193 行，但职责仍以 orchestration 和 observability 为主，阅读成本可控。
* `services/trading-service/src/core/compute.py`
  - 213 行，当前主要是 backend dispatch、batching、进程池复用；还没有出现明显的“混进 CLI/DB/参数解析”问题。
* `backfill_indicators.py` 的 `argparse` 和顶层 traversal
  - 不算小，但不是主要复杂度来源；先拆它们，减重收益不如先拆 fast kernels。

## First-Cut Split Proposal

建议第一刀只做“低耦合减重”，不要一上来重构 `core/` 调用链。

第一刀目标：

1. 先把 `backfill_indicators.py` 里的纯计算和注册表搬出去，让脚本退化成一个薄 orchestration/CLI。
2. 不改变任何回填策略，不顺手统一成 `core/`，先追求“挪位置，不改语义”。

建议拆成以下模块：

1. `services/trading-service/src/backfill/common.py`
   - 放共享 helper：
   - `_index_to_ts_strings()`
   - `_to_float_series()`
   - `_to_int_series()`
   - `_build_base_frame()`
   - `_wilder_smooth()`
   - `_trend_bias_series()`

2. `services/trading-service/src/backfill/fast_backfillers.py`
   - 放全部 `_backfill_*_fast()` 实现。
   - 这是第一刀最该拆的主体，因为它占了最大篇幅，而且函数大多是纯 `DataFrame -> DataFrame`。

3. `services/trading-service/src/backfill/registry.py`
   - 放 `FAST_BACKFILLERS` 和 `_broadcast_last_row()`。
   - 让 fast path 的注册与 fallback 不再埋在 CLI 脚本中。

4. `services/trading-service/src/backfill/plan.py`
   - 放 `_normalize_list()`、`_parse_int_overrides()`、`_build_bar_limit_map()`。
   - 这一步不是必须和第一刀同时做，但如果顺手拆，脚本入口会更薄。

5. 保留 `services/trading-service/src/scripts/backfill_indicators.py`
   - 只负责参数解析、调用 `backfill_all()`、打印日志。
   - 让它变成真正的脚本入口，而不是“入口 + 算法库 + 执行器 + 注册表”。

为什么第一刀先别碰别的：

* 先不要把 `backfill_symbol_interval*()` 直接并入 `core/`
  - 因为当前 `core` 本身边界还没完全收紧；这一步同时改“模块位置 + 执行模型”风险太高。
* 先不要拆 `engine.py` / `compute.py`
  - 这两个文件还没有成为当前维护瓶颈，拆了收益有限。
* 先不要按“一个指标一个文件”细碎拆分
  - 会增加文件数量和注册复杂度，但第一轮收益未必高；先集中抽成一个 `fast_backfillers.py` 更稳。

## Risks

1. Fast backfill 的公式并不等于实时 `indicator.compute()` 的逐 bar 历史重放。
   - 尤其 `fast` 和 `broadcast` fallback 本来就是性能取向的近似路径。
   - 所以第一刀只能做“位置迁移”，不应顺手改公式或试图统一成单一计算入口。

2. 脚本里硬编码了大量表名和中文列名。
   - 例如 `FAST_BACKFILLERS` 的 key、`_build_base_frame()` 产出的基础列、各指标的输出 schema。
   - 拆分时若同时做命名优化，很容易把“减重”变成“schema 风险变更”。

3. 当前异常处理大量是静默吞掉。
   - `services/trading-service/src/core/storage.py:99-116`、`services/trading-service/src/core/compute.py:90-99`、`services/trading-service/src/scripts/backfill_indicators.py:1150-1155`、`1194-1198` 都会压掉失败细节。
   - 这意味着拆分后即使行为回归，也可能不会立刻显性暴露；下一轮真动代码前，最好先补一批 characterization tests 或至少做样本回填对比。

4. `core/` 若后续继续收口，优先级应低于 backfill 大文件减重。
   - 现在最直接的维护成本来自 `backfill_indicators.py` 的超大体积与职责混装。
   - 更合理的顺序是：先把脚本减重，再决定是否把 backfill orchestration 逐步对齐到 `core/io` / `core/compute` / `core/storage` 的统一边界。
