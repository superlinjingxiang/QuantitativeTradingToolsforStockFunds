# 盈利验证策略 V2 与多资产复核

## 目的

提高短线策略证据的可复现性和风险可解释性，避免最终留出期偶然盈利直接升级执行候选。

## 进度

- [x] 增加趋势效率、Sharpe、Calmar、基准回撤指标。
- [x] 增加滚动前推跨窗口一致性降级。
- [x] 增加预测校准 BUY 门禁。
- [x] 固化十 ETF 和五股票加五 ETF 验证命令。
- [x] 完成真实多数据源 10 标的和 22 标的预测复核。
- [ ] 完成模拟盘成交偏差、容量、涨跌停和停牌压力验证。
- [ ] 完成按股票/ETF/黄金/债券资产类型分层参数验证。

## 当前结果

十 ETF 池 2/10 通过；混合池 3/10 通过；两组综合状态均为 WATCH。V2 改善了门禁质量，但尚未证明通用盈利能力。

## 复现

运行 python -m china_quant_platform.strategies.lab --universe etf10 和 --universe mixed10。完整配置与结果见 ../../research/SHORT_TERM_STRATEGY_VALIDATION_2026-07-12.md。

