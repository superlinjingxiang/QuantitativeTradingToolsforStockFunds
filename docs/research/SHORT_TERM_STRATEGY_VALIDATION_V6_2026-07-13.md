# 短线盈利验证策略 V6 研究记录

## 结论摘要

V6 不以提高回测收益为目标，而是修复 V5 自定义盈利验证器中过于理想的成交时点。V5 的入场已经使用“当日收盘确认、次日开盘买入”，但持有期、评分和趋势退出仍可能使用当日收盘数据并按同一收盘价卖出。V6 将这类退出统一改为下一交易日开盘执行，并对 A 股个股增加 T+1、停牌和一字涨跌停成交阻断。

修正后，十 A 股最终留出平均收益从 V5 的 `+5.71%` 降到 `-0.14%`，中位收益从 `+8.21%` 降到 `-2.44%`，仍为 `0/10 PASS`。这说明 V5 的 A 股收益改善包含明显的理想成交偏差。V6 的结果更保守、更接近可执行路径，但也明确证明当前短线策略尚未具备跨 A 股稳定赚钱能力。

## 执行模型改动

### 信号时序

- 入场：交易日 D 收盘后计算信号，最早在 D+1 开盘买入。
- 收盘退出信号：持有期到期、评分跌破和趋势破坏在 D 收盘后确认，最早在 D+1 开盘卖出。
- 跟踪止损：若开盘已经越过止损价，按开盘价成交；否则按止损触发价成交。
- 样本结束：仍使用最后收盘价做强制估值平仓，属于报告估值约定，不应理解为可保证成交的真实订单。

### A 股交易约束

- 普通 A 股个股启用 T+1，不允许买入当日卖出；当日触发止损时延迟到下一可交易日。
- 停牌或成交量为零时，不生成可成交买卖。
- 一字涨停时拒绝新买入，一字跌停时延迟卖出。
- 主板普通股票按 10% 涨跌幅识别，创业板和科创板按 20% 识别；当前验证池已排除 ST/退市风险标的。
- ETF 不套用 A 股个股 T+1/涨跌停识别。不同 ETF 的 T+0/T+1 规则仍需后续按产品类别细分。

规则依据：

- [上海证券交易所发布2026年交易规则并自2026年7月6日起施行](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)
- [上海证券交易所交易规则中的证券回转交易和科创板涨跌幅条款](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20250519_10779396.shtml)
- [深圳证券交易所关于回转交易品种的官方说明](https://www.szse.cn/disclosure/notice/general/t20190111_564052.html)
- [深圳证券交易所创业板20%涨跌幅规则说明](https://investor.szse.cn/knowledge/stock/chinext/t20200729_580056.html)

## 可审计输出

`ProfitBacktestResult` 和实验室 JSON 新增以下字段：

| 字段 | 含义 |
|---|---|
| `next_open_exit_count` | 收盘信号在下一交易日开盘执行的次数 |
| `same_day_exit_count` | 买入当日又卖出的实际次数 |
| `t_plus_one_deferral_count` | 因 A 股 T+1 延迟退出的次数 |
| `entry_rejection_count` | 因停牌或一字涨停拒绝买入的次数 |
| `exit_deferral_count` | 因 T+1、停牌或一字跌停延迟卖出的总次数 |

Vue/Electron 右侧“决策证据”新增“执行真实性”，直接展示这些统计。当前策略卡同时显示“次日开盘/T+1/涨跌停约束”，避免只在研究文档中说明。

## 正式参数

```text
strategy_version = profit-validation-short-v6
signal-derived exit = next trading day open
A-share T+1 = enabled
A-share suspension/one-price-limit blocking = enabled
target_annual_volatility = 20%
position_fraction = 25%-100%, no leverage
trailing_stop = 7.5%
base_round_trip_cost = 15bp
stress_round_trip_cost = 45bp
A-share max one-day return before entry = 3%
A-share max 21-day momentum before entry = 20%
```

## 真实数据结果

统一使用 7 年前复权日线、1 个月策略期限、每年最多 12 次交易、15bp 基础往返成本和 45bp 压力成本。数据截至 2026-07-13 左右，供应商、日期、K 线数量和数据 SHA256 继续进入报告快照。

| 验证池 | PASS | 平均最终收益 | 中位收益 | 平均超额 | 平均最大回撤 | 总交易数 | 次日开盘退出 | 同日退出 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 十 A 股 | 0/10 | -0.14% | -2.44% | -4.72% | -12.25% | 71 | 43 | 0 |
| 十 ETF | 2/10 | 17.42% | 14.82% | -5.44% | -10.39% | 103 | 70 | 1 |
| 五 A 股 + 五 ETF | 2/10 | 7.14% | 1.39% | -4.11% | -11.94% | 93 | 66 | 0 |

报告校验和：

- 十 A 股：`c5804ced332f2dc71dfdaa7e612f0b9df76821ab22aad3f3adde8a7a05d0e858`
- 十 ETF：`9cbf1ee9d42ee4ead076deaada69ec5a0f5674301229b770b5bd0ff306220086`
- 混合十标的：`f90648ea5881641d91c19c9779a52ffbd77613214aad646113ef9f63247411c8`

### V5 与 V6 对照

| 验证池 | 指标 | V5 | V6 |
|---|---|---:|---:|
| 十 A 股 | 平均收益 | 5.71% | -0.14% |
| 十 A 股 | 中位收益 | 8.21% | -2.44% |
| 十 A 股 | 平均最大回撤 | -11.64% | -12.25% |
| 十 ETF | 平均收益 | 17.81% | 17.42% |
| 十 ETF | 平均最大回撤 | -10.93% | -10.39% |
| 混合十标的 | 平均收益 | 9.95% | 7.14% |
| 混合十标的 | 中位收益 | 7.60% | 1.39% |
| 混合十标的 | 平均最大回撤 | -12.00% | -11.94% |

### 十 A 股逐标的

| 标的 | 状态 | 最终收益 | 最大回撤 | 交易数 | 次日开盘退出 |
|---|---|---:|---:|---:|---:|
| 600519 贵州茅台 | FAIL | -17.58% | -20.85% | 5 | 2 |
| 600036 招商银行 | WATCH | 13.44% | -7.30% | 7 | 7 |
| 601318 中国平安 | WATCH | 2.71% | -10.96% | 7 | 6 |
| 600276 恒瑞医药 | FAIL | -6.72% | -13.04% | 9 | 4 |
| 000333 美的集团 | FAIL | -16.62% | -20.60% | 8 | 4 |
| 600030 中信证券 | FAIL | -4.50% | -15.33% | 8 | 6 |
| 600900 长江电力 | FAIL | -6.22% | -8.89% | 7 | 7 |
| 300059 东方财富 | FAIL | -0.37% | -5.81% | 4 | 1 |
| 002475 立讯精密 | WATCH | 10.37% | -9.30% | 7 | 1 |
| 601899 紫金矿业 | WATCH | 24.13% | -10.42% | 9 | 5 |

真实三组样本中没有在候选成交日遇到可识别的一字涨跌停，故拒绝买入、T+1 延迟和跌停延迟聚合次数均为 0。确定性合成测试另外覆盖了一字涨停拒买、一字跌停延迟卖出和买入当日止损延迟到次日开盘，不能用“真实样本计数为零”推断规则未生效。

## 验证结果

- Ruff format、Ruff lint、mypy：通过。
- Python 全量回归：`276 passed`；FastAPI TestClient 有 1 条上游弃用警告。
- 发布审计：`RELEASE_AUDIT_OK`。
- Vitest：`1 passed`。
- Vite 生产构建：通过；ECharts 分包仍有超过 500kB 的体积告警。
- Playwright：`2 passed`。
- 真实联网复跑：`stock10`、`etf10`、`mixed10` 均为 10/10 成功取数。

## 当前边界与下一步

- 十 A 股聚合结果为 `FAIL`，不能把单只标的阶段性盈利包装成通用赚钱策略。
- ETF 有 1 次同日止损退出。ETF 是否允许 T+0 取决于产品类型，后续必须按交易所和产品规则细分，不应统一假设。
- 日线无法模拟盘口排队、封单量、开盘滑点、容量冲击和部分成交。
- 样本末尾按收盘价估值平仓仍是回测约定，不是现实成交保证。
- 当前版本继续保持 `RESEARCH_ONLY`，不执行真实下单。下一阶段优先接入模拟盘成交偏差和 ETF 交易制度分类，不再根据这次最终留出结果反向调参。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe stock10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe etf10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe mixed10
```
