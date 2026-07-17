# 2026-07-17 改动说明

## 用户可见现状

近期平台已完成 FastAPI + Vue + Redis 兼容迁移、Electron 默认 Vue 界面、行情与荐股缓存、自选/历史浏览持久化、浅色主题对比度、预测区间图层、手动账户输入和 A 股可买荐股边界。完整汇总见 `PROJECT_STATUS_2026-07-17.md`。

## 本轮策略研究

- 新增 `strategies.etf_rotation_validation`，对固定十ETF组合执行按时点回测、目标波动仓位、基础/压力成本和滚动前推验证。
- 新增 `strategies.etf_rotation_lab`，可从默认多数据源拉取真实历史并复现全样本和最后25%时间留出。
- ETF候选固定为252日正绝对动量、每21日选择最多2只、20%目标年化波动、下一交易日开盘执行。
- 新增至少3个完整滚动窗口硬门槛。最后25%虽收益+43.64%、超额+16.78%，但只有1折，因此结果为WATCH而不是PASS。
- 记录并拒绝股票5日无跟随退出和股票横截面动量候选；正式A股策略继续使用V7。

## 边界

- 本轮没有更改当前单标的策略建议、预测、账户评估或真实下单边界。
- ETF组合候选尚未进入模拟盘，未覆盖容量、冲击成本和ETF品种交易制度。
- 任何回测结果都不构成未来收益承诺。

## 复现

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.strategies.etf_rotation_lab --history-years 9 --oos-fraction 0.25
```

详细方法与结果见 `research/SHORT_TERM_STRATEGY_VALIDATION_V9_ETF_ROTATION_2026-07-17.md`。

## 预测区间校准 V2

- 修复21日预测逐日校准造成的标签重叠和有效样本虚高。
- 历史评估时隔离完整持有期，训练只使用当时已经兑现的标签，消除近端未来标签泄漏。
- 方向校准改为上涨/横盘/下跌三分类Brier，增加按期限缩放的最少独立样本门槛。
- `AnalysisReport` 新增结构化 `forecast_validation`，DecisionHub会对重叠、样本不足、覆盖率、下破率和Brier给出PASS/MISSING/FAIL。
- 模型版本升级为 `forecast.similar_regime_interval.v2`，缓存键升级到模式版本 `v2`，旧分析结果不会伪装成当前校准证据。
- 两组各十个真实标的完整取数：第一组平均覆盖82.67%、下破7.00%、三分类Brier 0.1938；第二组平均覆盖80.40%、下破9.67%、Brier 0.1987，聚合可靠性均为HIGH。
- 账户评估仍复用当前策略最终信号和仓位上限，没有增加第二套买卖策略。

详细方法、逐标的结果和复现命令见 `research/FORECAST_INTERVAL_VALIDATION_V2_2026-07-17.md`。校准通过只说明预测证据更可信，不代表策略能够保证盈利。

本轮验证：Ruff format、Ruff lint、mypy、300项Python全量回归和发布审计全部通过；保留1条FastAPI TestClient上游弃用警告。
