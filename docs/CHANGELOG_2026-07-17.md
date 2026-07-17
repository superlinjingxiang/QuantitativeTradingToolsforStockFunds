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
