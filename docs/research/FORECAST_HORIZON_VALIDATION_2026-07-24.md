# 预测终点周期验证（2026-07-24）

## 结论

短线策略的概率区间默认从 21 个交易日缩短为 **5 个交易日**；长线策略的概率区间使用 **10 个交易日**作为风险检查点。策略本身的持有与回测窗口不变：短线仍为 21 日，长线仍为 126 日。

这里的 5 日或 10 日是 `p05/p50/p95` **终点收益分布**，不是逐日价格路径。界面中的虚线只是把当前价连接到终点分位数，不能解释为每天都会沿虚线上涨或下跌。

## 研究依据

- Lehmann 的周频研究记录了当前赢家/输家在随后一周的短期反转，说明日到周是短期效应的重要观察尺度：[NBER Working Paper 2533](https://www.nber.org/papers/w2533)。
- Conrad 与 Kaul 的结果强调周频预期收益结构衰减较快，月度预期由更短周期结构累积而来：[Review of Financial Studies](https://academic.oup.com/rfs/article-abstract/2/2/225/1582726)。
- Medhat 与 Schmeling 表明短期反转或动量会随换手率变化，不能把一个固定方向机械外推一个月：[Review of Financial Studies](https://academic.oup.com/rfs/article-abstract/35/3/1480/6286969)。
- 中国市场研究发现动量主要出现在日频，周频和月频结论不同，支持把短线预测与月度持有窗口分开：[NBER Working Paper 31839](https://www.nber.org/papers/w31839)。
- Ang 与 Bekaert 对多国数据的有限样本修正提示，不应把表面上的长周期可预测性直接当作稳健证据：[NBER Working Paper 8207](https://www.nber.org/papers/w8207)。

这些论文提供周期选择动机，不直接证明本平台模型有效；最终默认值由下述同模型、同数据、同成本的样本外验证决定。

## 验证方法

- 模型：`forecast.similar_regime_interval.v2`。
- 标的：22 个，覆盖 A 股、宽基/行业/黄金/债券/海外 ETF 和指数。
- 数据：`multi_source` 日线，最近 6 年；本次 22/22 取数成功。
- 成本：每个终点收益扣除 15bp 往返成本。
- 周期：1、3、5、10、21 个交易日。
- 防泄漏：评估步长等于预测期，训练数据隔离完整预测期，仅统计互不重叠终点。
- 指标：90% 区间覆盖率、下沿跌破率、上涨/横盘/下跌三分类 Brier、终点收益中位绝对误差。

## 实测结果

| 预测终点 | 平均独立样本 | 区间覆盖 | 下沿跌破 | 三分类 Brier | 终点绝对误差中位数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 日 | 1254.6 | 89.17% | 5.05% | 0.1955 | 1.14% |
| 3 日 | 418.1 | 87.94% | 5.52% | **0.1903** | 2.06% |
| 5 日 | 250.7 | 87.69% | 5.81% | 0.1913 | 2.63% |
| 10 日 | 125.3 | 85.22% | 6.80% | 0.1931 | 3.87% |
| 21 日 | 59.5 | 81.58% | 8.79% | 0.1933 | 6.12% |

数值越低的 Brier 和终点误差越好；覆盖率应接近名义 90%，下沿跌破率应接近 5%。

## 选择说明

3 日的方向 Brier 略优于 5 日，但差异只有约 0.001；5 日仍保持约 88% 覆盖、约 6% 下破和 250 个以上平均独立样本，同时对应完整交易周，减少过度响应单日噪声和过高换手。因此短线产品默认采用 5 日。

10 日比 21 日拥有约两倍独立样本，覆盖率更高、下破更低、终点误差更小，因此长线策略只把 10 日区间作为近期风险检查。长线方向仍由 126 日策略验证、趋势和组合证据决定，不把 10 日价格区间冒充长期估值。

21 日结果不再作为默认图表预测：其区间覆盖比 5 日低约 6.1 个百分点，下破率高约 3.0 个百分点，终点绝对误差约为 5 日的 2.3 倍。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 1 --history-years 6
.\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 3 --history-years 6
.\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 5 --history-years 6
.\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 10 --history-years 6
.\.venv\Scripts\python.exe -m china_quant_platform.forecasting.lab --horizon-days 21 --history-years 6
```

本报告只验证概率区间校准，不证明策略可以持续盈利，也不构成交易指令。
