# 短线盈利验证策略 V7 研究记录

## 结论摘要

V7 在 V6 的次日开盘退出、A 股 T+1 和一字涨跌停约束上继续修正两个问题：日线跟踪止损不得使用当日尚未完成的最高价，A 股新开仓还必须经过可按时点复现的市场环境门槛。市场代理使用沪深300ETF `SSE:510300`，只有信号日可见的 21 日和 63 日动量都不低于 0% 时才允许新开 A 股个股仓位；代理数据不足时保守阻断，不用缺失数据放行。

统一参数复跑后，正式十 A 股平均收益由 V6 的 `-0.14%` 改善到 `+1.05%`，平均最大回撤由 `-12.25%` 改善到 `-10.36%`，但仍为 `0/10 PASS`。两个未参与参数锁定的确认池和影子池也都是 `0/10 PASS`：确认池平均亏损 `-7.93%`，影子池平均收益 `+1.23%` 但中位数为 `-1.49%`。因此当前证据只支持“市场过滤能减少部分逆势入场”，不支持“个股短线策略已经稳定赚钱”。

十 ETF 仍为 `2/10 PASS`，平均收益 `+18.30%`；但平均超额收益为 `-13.93%`，通用性仍不足。V7 继续保持 `RESEARCH_ONLY`，不得自动升级为模拟盘或真实下单候选。

## V7 改动

### 日线止损时点

- 计算当前交易日跟踪止损前，只允许使用前一交易日结束时已经确认的历史峰值。
- 当前交易日最高价只能在本日止损判断完成后加入下一日可见峰值。
- 保留 V6 的隔夜跳空规则：开盘低于止损价时按开盘价，盘中触发时按止损价。
- 单元测试通过修改未来市场数据和当日高点，验证过去信号与成交不会被未来信息改写。

### A 股市场环境门槛

```text
market_proxy = SSE:510300
short_lookback = 21 trading days
long_lookback = 63 trading days
allow_new_a_share_position = momentum_21d >= 0% and momentum_63d >= 0%
missing_proxy_history = block new position
ETF path = not applicable
```

每个信号日都只截取 `trade_date <= signal_date` 的代理 K 线。最终结果记录门槛状态、代理标的、证据日期、21/63 日动量和样本区间内被拒绝的候选入场次数。市场门槛只阻止新开仓，不阻止已有仓位按止损、减仓或卖出规则退出。

### 策略参数

```text
strategy_version = profit-validation-short-v7
A-share max one-day return before entry = 3%
A-share max 21-day momentum before entry = 15%
A-share market regime gate = 21d >= 0% and 63d >= 0%
signal-derived exit = next trading day open
A-share T+1 = enabled
A-share suspension/one-price-limit blocking = enabled
target_annual_volatility = 20%
position_fraction = 25%-100%, no leverage
trailing_stop = 7.5%
base_round_trip_cost = 15bp
stress_round_trip_cost = 45bp
```

15% 动量上限和市场门槛先用开发折比较并锁定，再运行确认池和影子池。本轮没有根据确认池或影子池结果再次调参，负结果原样保留。

## 真实数据验证

统一使用 7 年前复权日线、1 个月策略期限、每年最多 12 次交易、15bp 基础往返成本和 45bp 压力成本。三个 A 股池各 10 只且互不重叠；ETF 池和混合池沿用固定清单。数据供应商均为 `multi_source`，本轮所有池均无取数失败。

| 验证池 | PASS | 平均收益 | 中位收益 | 平均超额 | 平均最大回撤 | 总交易数 | 聚合状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| 正式十 A 股 | 0/10 | +1.05% | +3.55% | -3.53% | -10.36% | 59 | FAIL |
| 确认十 A 股 | 0/10 | -7.93% | -9.99% | +8.44% | -12.91% | 62 | FAIL |
| 影子十 A 股 | 0/10 | +1.23% | -1.49% | +12.47% | -9.79% | 65 | FAIL |
| 十 ETF | 2/10 | +18.30% | +17.26% | -13.93% | -10.45% | 102 | WATCH |
| 五 A 股 + 五 ETF | 2/10 | +8.89% | +2.27% | -6.70% | -10.30% | 87 | WATCH |

报告校验和：

- 正式十 A 股：`5ac5a33990de9b67f089158032bfbf9c44dd06eda12ac2b354475f90009f322c`
- 确认十 A 股：`1b4dbb96639c138404b8273a6b700be692ded66730a54873a2f831a2ca733d6d`
- 影子十 A 股：`ebe00935d41907cccd00893ab8d38bf2b2c771a5ecad2b5fe128096f424c9873`
- 十 ETF：`c98646dce7ed4cdc8ba71193a41d902584464db99571170f97603466d7a3e8bc`
- 混合十标的：`0c3ceace383bd689d81eeb43e556a43752eb926552974eae14beadc093123fdf`

### 结果解释

- 正式池从负收益改善为小幅正收益，但严格通过仍为 0，不能证明稳定赚钱。
- 确认池绝对收益明显为负。正超额来自基准同期跌幅更大，不能用“跑赢下跌基准”替代赚钱目标。
- 影子池平均为正但中位数为负，收益集中在少数标的，同样不具备横截面通用性。
- ETF 池有阶段性正收益和两个通过标的，但平均跑输各自基准，仍需做资产分类、滚动起点和模拟盘验证。
- 三套股票池结论不一致，说明单一沪深300方向门槛不能代替行业、个股质量和交易拥挤度判断。

## 四个决策模块

- `当前策略`：展示 V7、市场代理、21/63 日动量和当前门槛状态。
- `预期走势`：继续展示概率、收益区间、回撤和校准，不把市场门槛当成价格预测。
- `操作与风险`：下跌/减仓/卖出逻辑可以正常退出；若想新开 A 股仓位但市场门槛阻断或缺失，建议为 `ABSTAIN` 并写明原因。
- `决策证据`：展示 `PASS/BLOCKED/MISSING`、拒绝入场次数、次日开盘退出、T+1 和涨跌停执行统计。模拟盘证据缺失时始终保持 `RESEARCH_ONLY`。

手动账户输入继续复用当前标的的同一份策略、预测和回测结论，只根据计划资金、现金、成本价和持仓数量计算账户暴露及加减仓金额；账户模块没有第二套买卖策略，也不能绕过市场门槛和 DecisionHub。

## 金融依据与边界

V7 使用趋势持续性作为风险开关，并保留目标波动仓位思想。相关研究说明时间序列动量和波动管理可能改善某些样本的风险调整结果，但后续研究也提示其稳健性依赖样本、组合和实现方式。因此这些论文只支持候选机制，不构成本项目盈利证明：

- [Time Series Momentum](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)
- [Volatility Managed Portfolios](https://www.nber.org/papers/w22208)
- [On the performance of volatility-managed portfolios](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X)

当前仍未覆盖盘口排队、部分成交、容量冲击、真实滑点、ETF 分类交易制度和模拟盘偏差。任何历史收益都不代表未来收益，当前版本禁止真实下单。

## 工程验证

- Ruff format、Ruff lint、mypy：通过。
- Python 全量回归：`282 passed`；FastAPI TestClient 有 1 条上游弃用警告。
- 发布审计：`RELEASE_AUDIT_OK`。
- Vitest：`1 passed`。
- Vite 生产构建：通过；ECharts 分包仍有超过 500kB 的非阻断体积告警。
- Playwright：`2 passed`。
- 五组真实联网复跑全部完成，无供应商失败。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe stock10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe stock_confirm10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe stock_shadow10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe etf10
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe mixed10
```
