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

- 2026-07-12 代码变更：CHANGELOG_2026-07-12.md
- 短线策略 V2 真实验证：research/SHORT_TERM_STRATEGY_VALIDATION_2026-07-12.md
- 当前活动执行计划：exec-plans/active/0009-profit-validation-v2.md

## 变更规则

当实现改变产品行为时，应先更新最窄范围的事实源文档，再更新 `TRACEABILITY.md`、`spec/requirements.yaml`、测试和任务状态。除非某个文件明确标注为摘要，否则不得在多个文件中重复维护同一规范性需求。
