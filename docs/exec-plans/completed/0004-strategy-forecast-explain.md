# 策略预测与解释执行计划

## 目的和用户可见结果

在已完成的研究与回测核心之上，实现首批可解释量化策略、概率预测和GUI分析面板。完成后，用户可以基于固定数据快照运行ETF轮动和A股多因子基准，查看预测概率、收益/回撤区间、驱动因素、风险约束和不交易原因。

## 背景与仓库定位

TASK-001至TASK-016已完成，项目具备领域契约、数据供应商抽象、缓存、数据质量、市场规则、GUI基础、指标/因子、策略边界、回测执行、组合风险和报告回归。后续策略和预测必须复用这些能力，不得绕过数据质量、规则、风险或报告层。

## 范围

### 范围内

TASK-017至TASK-020。

### 范围外

真实资金交易、生产模型训练流水线、完整模拟账户、打包发布和真实供应商凭据接入。

## 需求编号与验收编号

FR-006至FR-009、FR-012、FR-014、FR-018、FR-020、AC-04、AC-05、AC-10、AC-12、T-12、T-13、T-17。

## 进度

- [x] ETF中期轮动基准策略；TASK-017。
- [x] A股多因子趋势基准策略；TASK-018。
- [x] 经过校准的预测引擎与不交易机制；TASK-019。
- [x] 分析报告、当前策略与预期走势面板；TASK-020。

## 意外情况与发现

2026-06-29：TASK-017完成。ETF轮动以研究基准形式实现，不标记生产可用；策略输出仍是 `RawSignal`，最终仓位和交易需要后续规则/风险层。

2026-06-29：TASK-018完成。A股多因子趋势基准使用时点股票池和时点因子快照，独立退出逻辑覆盖止损、持仓回撤和趋势破坏。

2026-06-29：TASK-019完成。预测引擎输出方向概率、收益分位数和期望回撤；样本不足、分布外、漂移和低置信度会返回ABSTAIN，不把诊断概率当作可交易建议。

2026-06-29：TASK-020完成。`AnalysisReport`成为策略、预测、风险和GUI面板之间的边界；陈旧数据和模型不确定都以ABSTAIN进入操作面板。

## 决策日志

2026-06-29：ETF池使用时点成员与特征输入，评分包含动量、绝对动量、趋势、波动率和平均相关性；不在策略内硬编码生产ETF名单。

2026-06-29：A股策略拒绝披露时间晚于 `as_of` 的因子快照，避免财务/因子可见性泄漏。

2026-06-29：预测层使用校准概率和区间表达，不输出单点收益承诺；不交易原因作为结构化枚举进入结果，供后续GUI和报告直接展示。

2026-06-29：GUI不直接运行策略或风险门禁，而是渲染ViewModel中的报告快照；报告必须携带同一证券、版本、数据快照和generation语义。

## 架构与接口

策略必须实现 `Strategy` 协议，只输出 `RawSignal` 与解释；预测输出必须以概率和区间表达；最终操作必须通过数据质量、规则、风险和组合约束。GUI面板只渲染应用状态，不直接运行策略或访问供应商。

## 里程碑

### 里程碑1——策略基准

实现TASK-017和TASK-018，提供ETF轮动与A股多因子趋势基准策略、固定夹具和基准报告。

### 里程碑2——预测与不交易

实现TASK-019，提供概率校准、收益分位数、分布外/漂移/样本不足时的不交易结果。

### 里程碑3——分析面板

实现TASK-020，把策略、预测、风险原因和解释接入GUI状态与测试。

## 具体实施步骤

从TASK-017开始，先建立ETF策略所需的时点证券池、动量/趋势/波动率/相关性逻辑和报告夹具，再扩展到A股多因子。

## 验证与验收

每个任务至少运行 `uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy src tests` 和 `uv run pytest`。策略和预测任务必须加入固定快照回归测试，不得将策略标记为生产可用。

## 可复现性、幂等性与恢复

策略夹具必须固定输入、版本、数据快照、规则版本和随机种子；预测校准和报告必须有稳定checksum；GUI测试使用offscreen Qt与确定性状态。

## 风险与缓解措施

- 过拟合风险：只交付基准策略和样本外报告，不标记生产可用。
- 概率误导风险：预测必须提供校准指标和不交易状态。
- GUI竞态风险：沿用 selection_generation 和状态快照，旧结果不得覆盖当前证券。

## 产物与备注

- `src/china_quant_platform/strategies/etf_rotation.py`：ETF时点池、轮动评分、RawSignal/Explanation和成本换手敏感性。
- `tests/unit/test_etf_rotation_strategy.py`：ETF池过滤、评分排序、研究状态、ABSTAIN路径和成本换手敏感性测试。
- `src/china_quant_platform/strategies/a_share_trend.py`：A股时点池、因子快照、横截面排名、多因子趋势评分、退出决策和分组拆解。
- `tests/unit/test_a_share_trend_strategy.py`：时点披露拒绝、市场/趋势过滤、独立退出、RawSignal/Explanation和分组拆解测试。
- `src/china_quant_platform/forecasting/engine.py`：校准概率预测、收益分位数、期望回撤、Brier/LogLoss/ECE和结构化ABSTAIN原因。
- `tests/unit/test_forecasting_engine.py`：READY概率/分位数、样本不足/分布外/漂移/低置信度不交易、校准指标和输入长度校验测试。
- `src/china_quant_platform/analysis/reports.py`：把策略评估、预测、数据健康和规则/风险门禁合成为完整 `AnalysisReport`。
- `src/china_quant_platform/ui/state.py`、`src/china_quant_platform/ui/viewmodel.py`、`src/china_quant_platform/ui/main_window.py`：策略、预期走势、操作与风险面板状态和渲染。
- `tests/unit/test_analysis_report_builder.py`、`tests/gui/test_analysis_panel.py`：报告合成、陈旧数据不交易、分布外不交易、GUI面板和旧generation丢弃测试。

## 结果与复盘

TASK-017至TASK-020已完成。首批研究策略、概率预测、不交易机制和GUI解释面板已形成闭环，但仍保持研究/模拟边界：策略只给原始信号，预测只给概率和区间，最终操作必须通过数据质量、规则、风险和报告层约束。
