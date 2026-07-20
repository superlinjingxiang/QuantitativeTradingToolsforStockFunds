# 文档索引

`docs/` 是本项目的需求与设计事实源。原始Word文档已被标准化和拆分，使Codex只需加载与当前任务相关的上下文。

| 领域 | 事实源 | 使用场景 |
|---|---|---|
| 产品范围与用户体验 | `product-specs/PRODUCT_SPEC.md` | 评估产品行为、优先级、用户故事、范围和发布门槛 |
| GUI行为 | `product-specs/GUI_SPEC.md` | 实现搜索、证券切换、图表、策略与预测面板 |
| 技术需求 | `technical/TECHNICAL_SPEC.md` | 实现基础设施、存储、数据、部署、安全和测试 |
| 架构 | `architecture/ARCHITECTURE.md` | 新增模块、修改依赖、定义协议 |
| 金融理论 | `domain/FINANCIAL_THEORY.md` | 设计因子、预测、组合和风险调整评估 |
| 中国市场规则 | `domain/MARKET_RULES.md` | 回测、可交易性、费用、T+规则、涨跌停和基金语义 |
| 数据契约 | `design/DATA_CONTRACTS.md` | 领域模型、供应商适配器、分析报告和错误契约 |
| 策略与模型 | `design/STRATEGY_MODEL_SPEC.md` | 信号、特征、校准、不交易机制和模型生命周期 |
| 回测 | `design/BACKTEST_SPEC.md` | 事件顺序、成交、成本、偏差控制和可复现性 |
| 验收 | `quality/ACCEPTANCE_CRITERIA.md` | 判断任务或版本是否通过 |
| 测试 | `quality/TEST_MATRIX.md` | 编写和选择测试 |
| 完成定义 | `quality/DEFINITION_OF_DONE.md` | 关闭任务和代码评审 |
| 发布清单 | `release/RELEASE_CHECKLIST.md` | 执行Windows打包、恢复、安全、冒烟测试和发布审计 |
| 追踪矩阵 | `TRACEABILITY.md` | 映射用户故事→需求→任务→测试 |
| 决策 | `DECISIONS.md` | 记录架构/产品决策和新增依赖 |
| 术语表 | `GLOSSARY.md` | 统一金融与工程术语 |
| 执行计划 | `exec-plans/active/` | 多模块或长周期实施工作 |

## 近期记录

- 截至 2026-07-20 的近期改动与当前状态：PROJECT_STATUS_2026-07-20.md
- 2026-07-20 ETF容量、冲击成本和交易制度改动：CHANGELOG_2026-07-20.md
- ETF组合容量、冲击成本与T+0/T+1验证：research/ETF_CAPACITY_IMPACT_VALIDATION_2026-07-20.md
- 截至 2026-07-17、覆盖至 `8231aec` 的近期改动与当前状态：PROJECT_STATUS_2026-07-17.md
- 2026-07-17 近期整合发布说明（架构、缓存、界面、荐股、账户、预测校准与 ETF 组合证据）：CHANGELOG_2026-07-17.md
- 截至 2026-07-14 的项目状态总览：PROJECT_STATUS_2026-07-14.md
- 2026-07-14 代码变更：CHANGELOG_2026-07-14.md
- 短线策略 V7 市场环境与独立股票池验证：research/SHORT_TERM_STRATEGY_VALIDATION_V7_2026-07-14.md
- 短线策略 V8 候选研究（未晋级）：research/SHORT_TERM_STRATEGY_VALIDATION_V8_CANDIDATE_2026-07-14.md
- 短线策略 V9 ETF组合候选研究（留出段WATCH）：research/SHORT_TERM_STRATEGY_VALIDATION_V9_ETF_ROTATION_2026-07-17.md
- 预测区间校准 V2（清除重叠标签与时点泄漏）：research/FORECAST_INTERVAL_VALIDATION_V2_2026-07-17.md
- ETF组合证据、DecisionHub与账户同链联动：research/ETF_ROTATION_DECISION_INTEGRATION_2026-07-17.md
- 短线策略资产分层门禁与失败候选复核：research/SHORT_TERM_STRATEGY_ASSET_CLASS_GATE_2026-07-14.md
- 2026-07-13 代码变更：CHANGELOG_2026-07-13.md
- 短线策略 V5 A股反追涨验证：research/SHORT_TERM_STRATEGY_VALIDATION_V5_2026-07-13.md
- 短线策略 V4 风险暴露与数据快照验证：research/SHORT_TERM_STRATEGY_VALIDATION_V4_2026-07-13.md
- 短线策略 V3 真实验证：research/SHORT_TERM_STRATEGY_VALIDATION_2026-07-13.md
- 当前盈利验证活动计划：exec-plans/active/0011-profit-validation-v4.md
- 已完成 V3 执行计划：exec-plans/completed/0010-profit-validation-v3.md
- FastAPI/Vue/Redis 活动计划：exec-plans/active/0008-fastapi-vue-redis-refactor.md
- 2026-07-12 代码变更：CHANGELOG_2026-07-12.md
- 短线策略 V2 真实验证：research/SHORT_TERM_STRATEGY_VALIDATION_2026-07-12.md
- 已完成 V2 执行计划：exec-plans/completed/0009-profit-validation-v2.md

## 变更规则

当实现改变产品行为时，应先更新最窄范围的事实源文档，再更新 `TRACEABILITY.md`、`spec/requirements.yaml`、测试和任务状态。除非某个文件明确标注为摘要，否则不得在多个文件中重复维护同一规范性需求。
