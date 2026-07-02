# TASK-027 ETF盈利验证核心子交付

## 目的和用户可见结果

实现第一版“策略到底能不能赚钱”的算法核心：用户可以用周期和每年最大交易次数约束，对ETF/基金优先策略做最终样本外回测，得到净收益、风险、交易次数和可信度证据。

## 背景与仓库定位

TASK-027要求建设盈利证据、可信回测和模拟盘验证闭环。本次只完成其中的参数化盈利算法、样本外验证和十标的ETF验证池；模拟盘偏差、容量压力、过拟合模型卡和DecisionHub完整EPV门禁仍是后续工作。

## 范围

### 范围内

- ETF/基金优先的动量、趋势、波动和回撤过滤策略。
- `1m/3m/6m/1y` 周期参数。
- 每年最大交易次数约束。
- 阈值训练/验证选择与最终样本外评估隔离。
- 滚动前推折、十标的ETF默认验证池、`ProfitabilityEvidence` 转换。

### 范围外

- 真实下单、券商API、生产策略状态。
- 模拟盘成交偏差、漏单/重复信号和容量压力完整实现。
- Electron或前端重构。

## 需求编号与验收编号

- 需求：US-09、FR-013至FR-015、FR-020至FR-022、C-006。
- 验收：覆盖EPV-001、EPV-002、EPV-004的一部分，并为EPV-006提供证据输入；EPV-003、EPV-005和完整EPV-006后续补齐。

## 进度

- [x] 2026-07-01 00:00Z — 完成盈利验证算法、默认ETF池和证据模型。
- [x] 2026-07-01 00:30Z — 完成单元测试、文档追踪和ADR记录。

## 意外情况与发现

- 当前shell找不到 `uv` 命令，但仓库 `.venv` 可用，验证使用 `.venv\Scripts\python.exe` 执行。
- 单纯收益百分比不足以判断策略质量，必须同步输出最大回撤、基准超额、胜率、交易次数和校准样本。
- 真实十ETF联网诊断首次暴露Yahoo日K兜底的OHLC和 `received_at` 契约清洗问题，已修复并补回归测试。
- 修复后十ETF均可拉取日K，数量为1306至1452根；当前算法平均样本外净收益8.14%，但0/10标的通过完整门槛，整体状态为FAIL，说明该版本只能作为研究基线，不能宣称具备通用赚钱能力。

## 决策日志

- 2026-07-01 — 交易次数按“每年最大完成交易次数”实现，便于不同周期比较。
- 2026-07-01 — 第一版默认使用ETF/基金验证池，降低单只股票停牌、涨跌停和财报事件对算法验证的干扰。
- 2026-07-01 — 阈值选择只使用训练/验证区间，最终样本外区间只评估，避免未来数据泄漏。

## 架构与接口

- `ProfitSeekingConfig`：周期、每年最大交易次数、成本、波动/止损和样本切分参数。
- `run_profit_strategy_backtest()`：单标的最终样本外验证。
- `run_profit_validation_lab()`：默认十ETF聚合验证。
- `profitability_evidence_from_validation()`：输出DecisionHub可消费的 `ProfitabilityEvidence`。

## 里程碑

### 里程碑1 — 参数化盈利算法

实现动量、趋势、波动、回撤评分和入场/出场逻辑。

### 里程碑2 — 样本外验证

实现阈值验证集选择、最终样本外评估、滚动前推和交易次数约束。

### 里程碑3 — 证据输出

输出收益、回撤、基准、胜率、交易次数、Brier分数、可信等级和checksum，并转换成DecisionHub证据。

## 具体实施步骤

1. 新增 `strategies.profit_validation`。
2. 从 `strategies.__init__` 导出公共接口。
3. 新增单元测试覆盖关键行为。
4. 更新TASKS、ADR、策略规格和追踪矩阵。

## 验证与验收

- `.venv\Scripts\python.exe -m pytest tests\unit\test_profit_validation_strategy.py`
- `.venv\Scripts\python.exe -m pytest tests\unit\test_eastmoney_provider.py`
- `.venv\Scripts\python.exe -m ruff format --check src\china_quant_platform\strategies\profit_validation.py tests\unit\test_profit_validation_strategy.py src\china_quant_platform\strategies\__init__.py`
- `.venv\Scripts\python.exe -m ruff check src\china_quant_platform\strategies\profit_validation.py tests\unit\test_profit_validation_strategy.py src\china_quant_platform\strategies\__init__.py`
- `.venv\Scripts\python.exe -m mypy src\china_quant_platform\strategies\profit_validation.py tests\unit\test_profit_validation_strategy.py`

## 可复现性、幂等性与恢复

相同K线、配置、周期和交易次数约束会生成相同交易记录、指标和checksum。算法不访问当前评估点之后的数据进行阈值选择。

## 风险与缓解措施

- 过拟合：阈值验证集选择和最终样本外区间隔离；后续继续补参数敏感性和多重检验模型卡。
- 误解收益：所有输出文案强调历史样本外结果不保证未来收益。
- 执行风险：当前只输出证据，不提交真实订单；缺少模拟盘证据时仍不能进入真实执行。

## 产物与备注

- `src/china_quant_platform/strategies/profit_validation.py`
- `tests/unit/test_profit_validation_strategy.py`
- `docs/DECISIONS.md` ADR-035
- `docs/design/STRATEGY_MODEL_SPEC.md`
- `TASKS.md`
- `docs/TRACEABILITY.md`

## 结果与复盘

本次完成TASK-027的盈利验证核心子交付。新增算法支持周期和每年最大交易次数两个关键用户入参，并能在十标的ETF池上生成聚合盈利证据。真实联网十ETF诊断显示该研究基线尚未通过通用赚钱门槛：平均样本外净收益为正，但相对基准超额不足，整体为FAIL。TASK-027仍保持进行中，下一步应补模拟盘偏差验证、容量/压力测试、参数敏感性和DecisionHub EPV完整门禁。
