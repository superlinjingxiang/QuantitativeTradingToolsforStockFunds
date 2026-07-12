# 短线盈利验证策略 V2 研究记录

## 研究目标

本记录验证 strategy.profit_validation_short_term 是否在不同市场和资产上具有可复现的历史样本外证据。目标是提高风险调整后的稳定性，不以单一标的、单一时间段或最高历史收益作为上线依据，也不承诺未来盈利。

## 本轮算法改动

- 策略版本升级为 profit-validation-short-v2 / profit-validation-long-v2。
- 增加趋势效率过滤：价格路径效率低于 10% 时不新开仓，减少横盘噪声中的频繁交易。该阈值来自 0%/10%/20%/30%/40% 的滚动前推比较，10% 的正收益折比例和折中位收益更均衡。
- 增加年化波动率、Sharpe、Calmar、基准最大回撤和滚动前推一致性指标。
- 最终留出区间即使通过，若有效滚动折少于 5、正收益折低于 55% 或折中位收益不为正，也会降级为 WATCH。
- PASS 不再只接受正超额收益。若总收益为正、Sharpe 至少 0.75，且最大回撤相对基准改善至少 20%，允许作为风险调整路径通过。
- BUY 候选增加预测校准门禁：校准样本至少 40、区间覆盖率至少 68%、下破率不高于 22%、方向 Brier 不高于 0.30。预测校准不足时降低等级和仓位，不把历史回测结果直接当成当前买入信号。
- 右侧“当前策略、预期走势、操作与风险、决策证据”继续使用同一套策略结果；展示新增 Sharpe、Calmar 和滚动前推一致性，不创建第二套文案策略。

## 可复现验证方法

统一配置：

- 策略模式：短线
- 期限：1个月
- 每年最多完成 12 次交易
- 历史长度：7年
- 阈值仅在训练/验证区间选择，最终留出区间只用于评估
- 开启滚动前推，不使用未来数据选择当前折参数

命令：

    .\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe etf10

    .\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe mixed10

    .\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 21 --history-years 7 --round-trip-cost-bps 15

etf10 包含宽基、成长、中小盘、金融、光伏、新能源、黄金、债券和境内纳指 ETF。mixed10 包含贵州茅台、招商银行、中国平安、恒瑞医药、美的集团，以及沪深300ETF、创业板ETF、纳指ETF、黄金ETF、国债ETF。

## 十只 ETF 结果

数据源 multi_source，10/10 取数成功。

| 指标 | 结果 |
|---|---:|
| 通过数 | 2/10 |
| 平均最终样本外收益 | 13.13% |
| 中位最终样本外收益 | 11.97% |
| 平均基准超额 | -17.54% |
| 平均最大回撤 | -17.02% |
| 总交易次数 | 101 |
| 综合状态 | WATCH |

代表性结果：

| 标的 | 状态 | 收益 | Sharpe | 最大回撤 | 滚动正收益折 |
|---|---|---:|---:|---:|---:|
| 纳指ETF 513300 | PASS/B | 22.55% | 1.06 | -9.91% | 66.7% |
| 黄金ETF 518880 | PASS/A（仅回测） | 61.85% | 1.55 | -20.26% | 83.3% |
| 创业板ETF 159915 | WATCH | 33.86% | 0.89 | -16.16% | 53.3% |
| 沪深300ETF 510300 | FAIL | -22.52% | -1.02 | -23.76% | 40.0% |

黄金 ETF 的回测证据较强，但当前预测校准覆盖率约 67.5%、下破率约 31.3%、Brier 约 0.265，未通过预测门禁，因此不能仅凭回测升级为当前 BUY。

## 五只 A 股加五只 ETF 结果

10/10 取数成功。

| 指标 | 结果 |
|---|---:|
| 通过数 | 3/10 |
| 平均最终样本外收益 | 2.33% |
| 中位最终样本外收益 | -2.21% |
| 平均基准超额 | -8.69% |
| 平均最大回撤 | -18.59% |
| 总交易次数 | 92 |
| 综合状态 | WATCH |

股票部分差异明显：中国平安最终留出收益约 4.85% 并通过当前规则，贵州茅台、美的集团分别约 -32.68%、-33.11%。这说明当前单一趋势动量结构不适合直接覆盖所有 A 股风格，后续需要加入市场状态、行业相对强弱和股票特有风险过滤。

## 预测校准结果

21日预测实验覆盖 22/22 个多资产标的：

- 平均区间覆盖率：86.76%
- 平均下破率：6.19%
- 平均方向 Brier：0.2231
- 平均绝对误差：5.32%
- 综合可靠性：MEDIUM

预测区间是历史相似状态下的概率分布，不是确定价格目标。界面上的当前建议还必须同时通过数据质量、回测、滚动一致性和风险门禁。

## 结论与边界

- V2 比 V1 增加了可解释的趋势效率、风险调整收益和滚动一致性门禁，减少“单一留出期表现好就通过”的风险。
- 10只 ETF 中只有 2 只通过，混合池中只有 3 只通过，整体均为 WATCH。当前证据不支持“策略普遍赚钱”或真实自动交易。
- 当前可用于研究筛选和模拟盘候选；在模拟盘成交偏差、容量、涨跌停/停牌压力和更长时间滚动证据完成前，执行状态保持 RESEARCH_ONLY。
- 后续优先做按资产类型分层策略、市场状态过滤、参数稳定区间与模拟盘偏差报告，而不是继续提高单次回测最高收益。

## 理论和方法参考

- Moskowitz、Ooi、Pedersen 的时间序列动量研究为中期收益延续提供了跨资产证据：https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf
- Moreira、Muir 讨论了高波动阶段降低风险暴露的风险管理思路：https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513
- 后续研究同时提醒波动管理并非在所有样本外场景系统性有效：https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
- Bailey 等人的回测过拟合概率与 Deflated Sharpe Ratio 方法用于提醒多次参数尝试会抬高虚假发现概率：https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf 和 https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
