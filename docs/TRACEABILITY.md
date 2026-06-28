# 需求追踪矩阵

本矩阵是从产品意图到实施任务和验证证据的标准桥梁。范围或行为变化时必须更新。

| 用户故事/需求 | 功能需求 | 验收 | 任务 | 测试 |
|---|---|---|---|---|
| US-01 搜索并选择证券 | FR-001、FR-002 | AC-01、AC-02 | TASK-004、TASK-009 | T-07、T-10 |
| US-02 查看实时/历史行情和周期 | FR-003、FR-004、FR-005 | AC-02、AC-03、AC-06 | TASK-005、TASK-008、TASK-010 | T-07、T-08、T-11、T-16 |
| US-03 理解当前策略 | FR-006、FR-012、FR-018 | AC-04、AC-10 | TASK-011、TASK-012、TASK-020 | T-13 |
| US-04 查看概率化预期走势 | FR-007 | AC-05、AC-10 | TASK-019、TASK-020 | T-12、T-13 |
| US-05 理解操作状态与原因 | FR-008、FR-009、FR-020 | AC-04、AC-06、AC-10 | TASK-015、TASK-020 | T-13、T-17 |
| US-06 运行并检查回测 | FR-013、FR-014 | AC-07、AC-08、AC-09 | TASK-013、TASK-014、TASK-016 | T-01至T-05、T-09、T-14、T-15、T-18 |
| US-07 正确分析ETF和场外基金 | FR-016 | AC-11 | TASK-017、TASK-023 | T-02、T-06、T-15 |
| US-08 学习金融概念 | FR-017 | AC-04、AC-05 | TASK-024 | 内容/GUI测试 |
| 市场概览与自选 | FR-010、FR-011 | AC-02 | TASK-021 | GUI/集成测试 |
| 模拟账户 | FR-015 | AC-08、AC-09、AC-12 | TASK-022 | T-08、T-09、T-18 |
| 报告与审计 | FR-019、FR-020 | AC-09、AC-10 | TASK-016、TASK-025 | T-09、T-14 |

## 需求编号来源

- 产品需求与用户故事定义在 `product-specs/PRODUCT_SPEC.md`。
- 工程和非功能需求定义在 `technical/TECHNICAL_SPEC.md` 与 `quality/ACCEPTANCE_CRITERIA.md`。
- 机器可读镜像位于 `../spec/requirements.yaml`。
