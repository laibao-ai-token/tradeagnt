# TradeCat Open Issues 汇总

> **汇总日期**: 2026-04-09
> **审核结果**: 架构项已全部收敛；007 系列进入收尾阶段

---

## ✅ 已完成 (Closed)

| Issue | 说明 | 状态 |
|-------|------|------|
| **PlanA 基金链路** | fund_symbols.py / fund_bridge.py 已落地 | ✅ 完成 |
| **004 新闻集成** | MVP 已可用，30+ checkboxes | ✅ 完成 |
| **003 交易代理** | Trade Agent 能力桥已构建 | ✅ 完成 |
| **001 ETF自动选基** | 验收标准全部达成 (12/12) | ✅ 完成 |
| **H1 硬编码路径** | 改为空，默认相对路径 | ✅ 已修复 |
| **C2 冷却存储竞态** | WAL + 写入重试 | ✅ 已修复 |
| **H4 规则数量** | 现在动态计数，不会错 | ✅ 已修复 |
| **C3 采集器串行阻塞** | 并发执行 + per-collector 超时隔离 | ✅ 已修复 |
| **H2 Timescale 双写冗余** | collector 主写链路统一到 raw_writer（去除 runtime fallback） | ✅ 已修复 |
| **H3 SQLite 列名混用** | DataWriter alias 映射 + 单测覆盖 | ✅ 已修复 |
| **H5 WebSocket 阻塞风险** | 有界异步 flush 队列 + 背压丢批计数 | ✅ 已修复 |
| **C1 RSS 静默失败** | per-feed 重试 + 退避 + 失败阈值冷却 | ✅ 已修复 |

---

## 🔴 Critical（已收敛）- 3个

### C1. RSS 新闻采集静默失败
- **位置**: `services/collector-service/src/collectors/news/rss.py`
- **现状**: 已补齐 per-feed 重试、退避、失败阈值冷却；支持冷却期跳过坏源并保留其他源采集
- **建议**: ✅ 已修复

### C2. 冷却存储多进程竞态 ✅ 已修复
- **修复内容**: 启用 WAL 模式 + busy_timeout + 写入重试

### C3. 采集器单线程串行
- **现状**: 已接入并发执行 + per-collector 超时隔离（`collector_timeout_seconds`）+ 失败重试退避（`collector_max_retries` / `collector_retry_backoff_seconds`），单个 collector 卡死不会阻塞其他 collector 的完成态汇总
- **建议**: ✅ 已修复（继续观察超时阈值取值）

---

## 🟠 High（已收敛）- 5个

### H1. 硬编码路径 ✅ 已修复

### H2. Timescale 双写路径冗余
- **现状**: WSCollector + MetricsCollector 已强制 raw writer 契约（`start_batch` + `upsert_*`），runtime 热路径不再回退 `adapters/timescale.py`；历史兼容层仅保留在回填/扫描模块
- **建议**: ✅ 已修复

### H3. SQLite 列名混用
- **现状**: DataWriter 已有英文键到中文主键列的 alias 映射，并有单测覆盖 `symbol/interval/bucket_ts -> 交易对/周期/数据时间`
- **建议**: ✅ 已修复

### H4. 规则数量不一致 ✅ 已修复
- **现状**: 动态计算，不会出错

### H5. WebSocket 阻塞风险
- **现状**: WS flush 改为有界异步队列，队列满时丢弃最旧批次并计数，降低回调线程阻塞
- **建议**: ✅ 已修复（持续观察丢批监控）

---

## 📋 007 交易系统推进状态

| ID | Issue | 状态 |
|----|-------|------|
| 007-01 | Domain Read Models | ✅ 已实现（待关闭） |
| 007-02 | Agent Context Packer | ✅ 已实现（待关闭） |
| 007-03 | Paper Trading Workflow | ✅ 已实现（待关闭） |
| 007-04 | Unified Risk Guard | ✅ 已实现（待关闭） |
| 007-05 | Execution Protocol | ✅ 已实现（待关闭） |
| 007-06 | MVP Design | ⏳ Draft 待评审 |

---

## 总结

| 状态 | 数量 |
|------|------|
| ✅ 已完成/已修复 | 13 个 |
| 🟡 007 进行中 | 0 个 |
| ⏳ 007 待设计评审 | 1 个 |
| ⚠️ 待观察 | 0 个 |
