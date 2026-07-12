# 2026-07-12 近期改动说明

## 策略与验证

- 盈利验证策略升级到 V2，短线和长线由统一 profit_strategy_config() 生成，桌面端、FastAPI 和验证实验室不再维护重复参数。
- 新增趋势效率过滤、Sharpe、Calmar、基准回撤和滚动前推一致性。
- DecisionHub 增加风险调整比较路径；较低总收益只有在 Sharpe 和回撤改善同时达标时才允许通过。
- 当前 BUY 候选增加预测校准门禁，样本、区间覆盖率、下破率或 Brier 不达标时自动降级。
- 新增可复现策略验证命令，支持 etf10 和 mixed10 两个十标的池。

## 界面证据

- 回测状态卡增加 Sharpe。
- 决策证据增加净收益、最大回撤、Sharpe 和滚动前推一致性。
- 右侧四个模块继续使用同一份策略、预测、回测和门禁结果，不生成独立账户策略或展示型假信号。

## 当前验证结论

- 十 ETF 池：2/10 通过，平均最终样本外收益 13.13%，整体 WATCH。
- 五 A 股加五 ETF 池：3/10 通过，平均收益 2.33%、中位收益 -2.21%，整体 WATCH。
- 21日预测多资产实验：22/22 取数成功，平均覆盖率 86.76%，平均 Brier 0.2231，可靠性 MEDIUM。
- 当前仍不支持真实下单，不保证收益；详细证据见 research/SHORT_TERM_STRATEGY_VALIDATION_2026-07-12.md。

## 发布前检查

- Ruff format、Ruff lint、mypy：通过。
- Python 全量回归：261 passed。
- Vue/Vitest：1 passed。
- Vite 生产构建：通过；ECharts 图表分包仍有体积告警，列为后续加载性能优化。
- Playwright：2 passed。
- mixed10 七年真实数据命令：通过，10/10 标的成功取数。
