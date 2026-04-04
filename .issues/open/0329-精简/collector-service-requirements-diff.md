# collector-service requirements diff

## 1. 交集（两个服务都依赖）
- `psycopg[binary,pool]>=3.1.0`
- `aiohttp>=3.9.0`
- `ccxt>=4.0.0`
- `cryptofeed>=2.4.0`
- `requests>=2.31.0`

## 2. data-service 独有（markets-service 不包含）
- 无独有依赖。data-service 的所有包都已被 markets-service 覆盖。

## 3. markets-service 独有（data-service 不引用）
- `pydantic>=2.0`
- `python-dotenv>=1.0.0`
- `akshare>=1.14.0`
- `baostock>=0.8.8`
- `yfinance>=0.2.40`
- `pandas-datareader>=0.10`
- `fredapi>=0.5.0`
- `QuantLib>=1.30` *(高风险：C++ 绑定，需确认运行环境的编译依赖)*
- `openbb>=4.0` *(可选/高风险：跨源聚合，若仓库需要可考虑可选安装)*
- `pandas>=2.0`
- `numpy>=1.24`

## 4. 版本冲突
- 当前两个 requirements 之间未发现版本冲突；重复依赖版本一致，均已保留原约束。

## 5. 合并策略
1. 使用 markets-service 的分组注释保持文档清晰，data-service 仅依赖的包已经在该列表中体现，所以最终文件只需补充缺失模块。
2. 共享依赖保留现有版本约束，不工业化统一其它版本号，防止引入不必要的调试范围。
3. 对于 `QuantLib` 和 `openbb` 这样的可选/高风险包，保留原始版本，并在文档或部署方案中标注：
   - `QuantLib` 可能需要系统级编译依赖，集成前请在目标环境做编译验证。
   - `openbb` 可按需安装，尤其在轻量部署时应明确是否为必要依赖。
4. 如未来需要缩小依赖集，可优先从 markets-service 独有部分剔除不必要的聚合/衍生品库，再重新评估差异。

## 6. 自检说明
- 已确认合并后的 requirements 只有唯一条目、格式为 `<包名><约束>`，无重复包名。由于网络/离线限制，本地未执行 `pip install --dry-run`。
