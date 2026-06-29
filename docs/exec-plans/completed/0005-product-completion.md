# 产品完善执行计划

## 目的和用户可见结果

完成TASK-021至TASK-025，让MVP从研究/解释闭环继续扩展到市场概览、自选列表、模拟账户、基金分析、知识中心和发布审计。完成后用户可以在同一桌面应用中查看市场状态和自选信号，使用模拟账户验证信号，分析场外基金，阅读上下文帮助，并获得可复现的Windows发布清单。

## 背景与仓库定位

TASK-001至TASK-020已完成。项目已有可复现Python仓库、领域契约、数据供应商抽象、缓存、数据质量、市场规则、GUI外壳、图表、指标/因子、策略、回测、执行、组合风险、报告、ETF/A股研究策略、概率预测和AnalysisReport GUI面板。后续任务必须继续复用领域模型、数据质量、规则、风险和报告边界。

## 范围

### 范围内

TASK-021、TASK-022、TASK-023、TASK-024、TASK-025。

### 范围外

真实下单、真实供应商凭据、生产模型训练流水线和超出MVP的联网服务。

## 需求编号与验收编号

FR-010、FR-011、FR-015、FR-016、FR-017、FR-019、FR-020、AC-01至AC-12、NFR-01至NFR-08、T-02、T-06、T-08、T-09、T-15、T-18。

## 进度

- [x] 市场概览、指数与自选列表；TASK-021。
- [x] 模拟交易经纪与账户；TASK-022。
- [x] 场外基金分析模块；TASK-023。
- [x] 知识中心与上下文金融帮助；TASK-024。
- [x] 打包、恢复、安全与发布审计；TASK-025。

## 意外情况与发现

2026-06-29：TASK-021完成。市场概览使用标准 `Quote` 计算指数变动、广度、成交额和波动状态；自选信号更新不改变当前选中证券。

2026-06-29：TASK-022完成。模拟账户复用回测执行模拟器、市场规则和组合记账；数据陈旧、T+1可卖数量和部分成交偏差都有结构化记录。

2026-06-29：TASK-023完成。场外基金确认和分析只接受正式 `FundNav`，估算净值会被拒绝进入确认或风险分析路径。

2026-06-30：TASK-024完成。知识中心使用结构化 `HelpTopic`，默认主题覆盖K线、T+、ETF、净值、回撤、期望值和概率校准；内容校验拒绝收益承诺词，并要求显式区分国际理论与中国市场规则。

2026-06-30：TASK-025完成。发布审计使用结构化 `ReleaseAuditReport` 覆盖AC、NFR和完成定义，PyInstaller spec提供Windows one-folder打包入口，CLI扫描仓库嵌入式凭据。

## 决策日志

2026-06-29：市场概览和自选列表归属ViewModel状态快照，左侧Widget只渲染并触发显式选择事务。

2026-06-29：模拟经纪不预留真实下单方法，只暴露纸面 `submit_order()`；恢复机制使用可序列化 `SimulationAccountState` 快照。

2026-06-29：场外基金使用独立 `funds` 模块处理确认、费用和风险比较，不复用交易所成交价格语义。

2026-06-30：知识中心内容不写入Widget，统一由 `knowledge` 模块提供结构化条目和相关度搜索，GUI只渲染ViewModel状态。

2026-06-30：发布阶段不把大型安装目录纳入常规测试产物；常规门禁验证PyInstaller工具、spec、发布审计和无凭据扫描，真实发布工作站按同一spec生成 `dist/china-quant-platform/`。

## 架构与接口

市场概览与自选必须进入ViewModel状态快照，GUI只渲染快照并通过已有选择事务切换证券。模拟账户必须复用市场规则、执行成本、组合记账和风险门禁，不得出现真实下单路径。基金分析必须保留正式净值和估算净值边界。知识中心是只读帮助内容，不得承诺收益。发布审计必须记录可复现命令、清单和凭据排除证据。

## 里程碑

### 里程碑1——市场概览与自选

实现TASK-021，提供指数看板、市场广度、成交额、波动状态、分组自选和当前信号显示。

### 里程碑2——模拟账户与基金分析

实现TASK-022和TASK-023，提供无真实下单路径的模拟经纪/账户，以及场外基金正式净值语义和风险比较。

### 里程碑3——帮助与发布审计

实现TASK-024和TASK-025，提供上下文知识中心、恢复/安全/打包清单和最终验收证据。

## 具体实施步骤

按TASKS.md顺序推进。每个任务完成后更新TASKS、TRACEABILITY、DECISIONS、本执行计划和MANIFEST，并提交推送。

## 验证与验收

每个任务至少运行 `uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy src tests`、`uv run pytest` 和 `uv run python -m china_quant_platform --version`。涉及GUI的任务使用offscreen Qt测试；涉及清单的任务刷新并校验 `MANIFEST.sha256`。

## 可复现性、幂等性与恢复

所有夹具使用确定性输入；ViewModel更新必须支持generation或证券ID过滤；模拟账户恢复和发布审计必须有固定文件和测试证据。

## 风险与缓解措施

- GUI状态漂移：所有面板通过状态快照更新，旧结果不得覆盖当前证券。
- 真实交易误用：模拟账户不得包含券商提交接口。
- 基金净值越界：场外基金正式净值和估算净值使用不同类型。
- 发布遗漏：最终清单必须验证凭据排除、MANIFEST和测试命令。

## 产物与备注

- `src/china_quant_platform/market/overview.py`：指数快照、市场广度、成交额、波动状态和数据健康。
- `src/china_quant_platform/ui/state.py`、`src/china_quant_platform/ui/viewmodel.py`、`src/china_quant_platform/ui/main_window.py`：市场概览、自选分组、当前信号和左侧列表渲染。
- `tests/unit/test_market_overview.py`、`tests/gui/test_market_watchlist.py`：市场概览计算、陈旧状态、自选分组信号、当前选择稳定和GUI列表测试。
- `src/china_quant_platform/simulation/broker.py`：模拟订单、成交、账户状态、盈亏指标、偏差记录、JSON恢复和无真实下单边界。
- `tests/unit/test_simulation_broker.py`：成交入账、陈旧数据阻断、T+1拒绝、部分成交偏差、恢复快照和真实下单路径缺失测试。
- `src/china_quant_platform/funds/analysis.py`：场外基金正式净值申赎确认、费用、到账日期、周/月风险和基准比较。
- `tests/unit/test_fund_analysis.py`：正式净值确认、截止时间顺延、赎回现金、估算净值隔离和风险比较测试。
- `src/china_quant_platform/knowledge/center.py`：结构化帮助主题、安全校验、相关度搜索和上下文帮助。
- `src/china_quant_platform/ui/state.py`、`src/china_quant_platform/ui/viewmodel.py`、`src/china_quant_platform/ui/main_window.py`：知识中心状态、搜索、选题和GUI页签渲染。
- `tests/unit/test_knowledge_center.py`、`tests/gui/test_knowledge_center_gui.py`：主题覆盖、收益承诺词拒绝、国际理论/中国市场规则区分、上下文帮助和GUI筛选渲染测试。
- `src/china_quant_platform/release/audit.py`：发布命令、迁移、凭据策略、恢复/观测、AC/NFR/完成定义覆盖和凭据扫描。
- `packaging/china_quant_platform.spec`：Windows PyInstaller one-folder打包入口。
- `docs/release/RELEASE_CHECKLIST.md`、`.env.example`：发布清单和无真实凭据的环境变量模板。
- `tests/unit/test_release_audit.py`、`tests/integration/test_release_scan.py`：发布覆盖、CLI、凭据检测和仓库级无嵌入式凭据扫描测试。

## 结果与复盘

TASK-021至TASK-025已完成。市场概览、自选、模拟账户、场外基金、知识中心和发布审计均有代码、测试、追踪矩阵、决策记录和MANIFEST证据。最终发布前仍需在Windows发布工作站按 `docs/release/RELEASE_CHECKLIST.md` 生成并归档实际 `dist/china-quant-platform/` 产物。
