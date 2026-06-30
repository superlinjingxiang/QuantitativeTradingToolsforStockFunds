# MVP任务待办列表

必须按依赖关系顺序完成任务。除非活动执行计划明确允许，否则Codex每次运行只实现一个任务，或一个紧密耦合的任务组。

状态说明：`[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 已阻塞。

## 阶段0——仓库与契约

### [x] TASK-001——搭建可复现的Python仓库
- 依赖：无
- 阅读：`AGENTS.md`、`docs/architecture/ARCHITECTURE.md`、`docs/quality/DEFINITION_OF_DONE.md`
- 交付：`pyproject.toml`、`src/`目录结构、测试目录、配置/日志骨架、锁文件方案、CI骨架、`.gitignore`。
- 验收：可在干净环境安装；导入冒烟测试通过；测试、代码检查和类型检查命令有文档且全部通过。
- 完成证据：2026-06-28 完成 `uv.lock`、`src/china_quant_platform/`、测试目录、CI骨架和运行时骨架；`ruff format --check`、`ruff check`、`mypy src tests`、`pytest` 和 `python -m china_quant_platform --version` 均通过。

### [x] TASK-002——实现标准领域模型与错误分类
- 依赖：TASK-001
- 阅读：`docs/design/DATA_CONTRACTS.md`、`spec/contracts/*.json`
- 交付：有类型的ID、证券、行情、K线、基金净值、数据健康、分析报告模型及类型化错误。
- 验收：Schema与模型可双向转换；非法概率、非法时间戳和缺少来源信息的可交易报告会被拒绝。
- 完成证据：2026-06-28 完成 `domain` 领域枚举、ID别名、证券/行情/K线/基金净值/数据健康/分析报告/回测配置/规则模型和类型化错误；Schema往返、非法概率、非法时间戳、可交易报告来源信息和基金净值隔离测试通过。

### [x] TASK-003——实现数据供应商协议与确定性假供应商
- 依赖：TASK-002
- 交付：具备能力声明的协议、历史/实时假供应商、取消与限流行为。
- 验收：供应商契约测试通过；领域模块不依赖具体供应商SDK。
- 完成证据：2026-06-28 完成 `MarketDataProvider` 协议、请求模型、能力声明、异步限流器和 `DeterministicFakeMarketDataProvider`；搜索、Quote、日线K线、实时订阅、公司行为、基金正式净值、缺能力错误、取消和限流测试通过。

## 阶段1——数据、规则与存储

### [x] TASK-004——证券主数据与搜索索引
- 依赖：TASK-002、TASK-003
- 需求：FR-001、AC-01
- 交付：标准证券实体、别名、时点状态、本地模糊搜索和最近搜索。
- 验收：T-10通过；P95搜索性能达到基准夹具要求。
- 完成证据：2026-06-29 完成 `SecurityMasterService`、时点 `SecurityMasterRecord`、`SecuritySearchResult` 和最近访问 LRU；代码/名称/别名去重搜索、模糊匹配、时点状态、非活跃过滤、最近搜索和2000证券夹具P95<300ms测试通过。

### [x] TASK-005——历史/实时数据网关与缓存
- 依赖：TASK-003
- 需求：FR-003、FR-004、AC-06
- 交付：标准化K线与行情、Parquet分区、增量补缺、实时订阅状态。
- 验收：陈旧、重复、OHLC合法性测试通过；支持取消和重连；追加数据不得触发全量刷新。
- 完成证据：2026-06-29 完成 `HistoricalBarCache`、`MarketDataGateway`、实时订阅状态和 `pyarrow` Parquet 分区读写；分区读写、重复时间戳、损坏OHLC、缓存幂等追加、缺口计算、增量补缺、陈旧Quote阻断、订阅取消和断线重连测试通过。

### [x] TASK-006——数据质量门禁与对账
- 依赖：TASK-005
- 交付：新鲜度、完整性、一致性和授权检查，并带有阻断等级。
- 验收：T-08、T-16通过；被阻断的数据不得生成最终可交易信号。
- 完成证据：2026-06-29 完成 `DataQualityService`、`DataQualityPolicy`、结构化质量问题、健康状态报告和信号阻断断言；重复K线、非法OHLC、缺失K线、陈旧Quote、缺失字段、未授权供应商、跨源Quote不一致、健康数据放行和被阻断数据拒绝可交易报告测试通过。

### [x] TASK-007——按生效日期解析的中国市场规则引擎
- 依赖：TASK-002
- 阅读：`docs/domain/MARKET_RULES.md`
- 交付：规则存储与解析、涨跌停、停牌、手数/最小价位、可卖数量、费用和基金语义。
- 验收：T-02至T-06、T-15通过；缺失规则时必须关闭式失败，不得猜测。
- 完成证据：2026-06-29 完成 `InMemoryRuleRepository`、`MarketRuleEngine`、订单校验、涨跌停价格带、停牌、手数/最小价位、T+可卖数量、费用、场外基金正式净值语义和信息可见性检查；有效期边界、证券专属规则优先、缺规则关闭式失败、T+1、涨停无流动性、停牌、费用、基金估算净值隔离和披露前不可见测试通过。

## 阶段2——GUI行情工作台

### [x] TASK-008——PySide6应用外壳与状态模型
- 依赖：TASK-001、TASK-002
- 交付：主窗口、MVVM/MVP状态、导航页签、后台任务抽象、数据健康横幅。
- 验收：Qt主线程保持响应；能够演示取消和类型化错误状态。
- 完成证据：2026-06-29 完成 `MainWindow`、`ApplicationViewModel`、`CancellableQtTask`、`AppUiState`、GUI CLI入口和offscreen GUI测试；状态健康映射、健康横幅、非阻塞取消、类型化错误可见性和PySide6导入测试通过。

### [x] TASK-009——搜索与原子化证券切换
- 依赖：TASK-004、TASK-005、TASK-008
- 需求：FR-001、FR-002、AC-01、AC-02
- 交付：搜索控件、键盘操作、`selection_generation`、旧订阅取消。
- 验收：T-07、T-10通过。
- 完成证据：2026-06-29 完成 `ApplicationViewModel` 搜索/选择事务、`SearchCandidateState`、300ms防抖搜索结果列表、上下/回车键盘确认、选择时取消旧任务和 generation-aware 旧结果丢弃；本地证券搜索、键盘候选、旧任务取消、旧代结果不覆盖新证券和T-10搜索回归测试通过。

### [x] TASK-010——实时/历史图表工作区
- 依赖：TASK-005、TASK-008、TASK-009
- 需求：FR-003、FR-004、FR-005、AC-03
- 交付：折线/K线/成交量图、周期切换、叠加层、复权状态、增量更新、预测与信号图层。
- 验收：T-11及GUI性能目标通过。
- 完成证据：2026-06-29 完成 `ChartState`、`ChartPointState`、`PriceChartWidget`、周期/范围/复权/叠加层控件、历史K线加载和实时Quote增量更新；图表点渲染、实时追加、旧generation忽略、跨标的Quote忽略、改变范围/叠加层保持当前证券和复权模式测试通过。

## 阶段3——研究与回测核心

### [x] TASK-011——确定性指标与因子注册表
- 依赖：TASK-002、TASK-005
- 交付：版本化SMA/EMA/MACD/RSI/ATR/布林带/VWAP，以及收益率、波动率、回撤、相对强弱和因子元数据。
- 验收：预热期和缺失值测试通过；不得访问未来数据；缓存键可确定复现。
- 完成证据：2026-06-29 完成纯函数 `indicators` 指标库、`IndicatorSpec`/`IndicatorCacheKey`、收益/波动/回撤/相对强弱计算、`FactorMetadata`、`FactorRegistry` 和默认版本化因子；预热期、缺失值、未来值隔离、因子元数据校验、重复注册和缓存键排序无关性测试通过。

### [x] TASK-012——策略接口与解释模型
- 依赖：TASK-011
- 交付：策略协议、原始信号、适用条件、失效条件、解释和版本元数据。
- 验收：策略不得直接产生最终订单，也不得绕过风险和规则层。
- 完成证据：2026-06-29 完成 `Strategy` 协议、`StrategyContext`、`WarmupSpec`、`StrategyMetadata`、`RawSignal`、`Explanation` 和 `evaluate_strategy()`；`RawSignal` 强制保留数据质量/规则/风控门禁且禁止订单/最终信号字段，预热不足、身份不一致、解释不匹配和条件缺失测试通过。

### [x] TASK-013——事件驱动回测内核
- 依赖：TASK-005、TASK-007、TASK-012
- 需求：FR-013、AC-07
- 交付：事件循环、时钟/交易时段、订单/成交/拒绝/部分成交事件、取消和审计。
- 验收：T-01、T-04、T-05、T-09通过。
- 完成证据：2026-06-29 完成 `BacktestEventLoop`、`BacktestClock`、`BacktestEngine`、`OrderIntent`、`ExecutionReport`、确定性执行模拟器、取消令牌和结果checksum；事件优先级、策略在市场事件后评估、订单晚于信号、规则拒绝、部分成交、取消和重复运行checksum一致测试通过。

### [x] TASK-014——执行、成本、流动性与公司行为
- 依赖：TASK-007、TASK-013
- 需求：AC-08、AC-11
- 交付：佣金、税费、滑点、价差、流动性、涨跌停、延迟模型，以及公司行为处理器。
- 验收：T-02至T-06、T-15、T-18通过。
- 完成证据：2026-06-29 完成 `RuleBasedCostModel`、固定bps滑点、固定价差、参与率流动性、固定延迟、`CorporateActionProcessor`，并接入 `DeterministicExecutionSimulator`；费用/税费、滑点/价差、参与率部分成交、延迟、涨停无对手方流动性拒绝、分红和拆股测试通过。

### [x] TASK-015——组合与风险引擎
- 依赖：TASK-013、TASK-014
- 需求：FR-008、AC-08
- 交付：现金、持仓、可卖数量、仓位计算、集中度、相关性、流动性和回撤门禁。
- 验收：T-17、T-18通过。
- 完成证据：2026-06-29 完成 `PortfolioState`、`Position`、`PortfolioEngine`、组合对账、`RiskLimitConfig`、`RiskEngine` 和风险预算仓位计算；买入/卖出成交入账、可卖数量阻断、现金+市值对账、集中度/总敞口/现金缓冲/流动性/回撤/相关性门禁和手数取整测试通过。

### [x] TASK-016——指标报告与确定性回归夹具
- 依赖：TASK-013、TASK-015
- 需求：FR-014、FR-019、FR-020、AC-09、AC-10
- 交付：绩效、校准和成本报告；交易流水；CSV/HTML导出；运行清单和校验和。
- 验收：T-09、T-14以及固定快照回归测试通过。
- 完成证据：2026-06-29 完成 `BacktestReportBuilder`、绩效指标、校准指标、成本汇总、交易流水、运行清单、稳定checksum、CSV交易导出和HTML报告导出；固定报告夹具checksum `cedc0dd803c8b279fd68cf5e2b4514bc5e7c053d9dcf634db439392b7bf9cdee` 回归测试通过。

## 阶段4——策略、预测与解释

### [x] TASK-017——ETF中期轮动基准策略
- 依赖：TASK-011至TASK-016
- 交付：时点ETF池、动量/趋势/波动率/相关性逻辑和基准报告。
- 验收：提供样本外滚动报告、成本与换手敏感性；不得直接标记为生产可用。
- 完成证据：2026-06-29 完成 `EtfRotationStrategy`、时点ETF池成员、动量/绝对动量/趋势/波动/相关性评分、研究状态元数据和成本/换手敏感性；ETF池过滤、评分排序、RawSignal/Explanation边界、不选中时ABSTAIN和成本换手敏感性测试通过，策略状态保持 `RESEARCH`。

### [x] TASK-018——A股多因子趋势基准策略
- 依赖：TASK-011至TASK-016
- 交付：合格股票池、因子预处理/排序、市场过滤、独立退出逻辑和基准报告。
- 验收：使用时点披露与时点股票池；提供市场状态、年份、行业拆解和敏感性报告。
- 完成证据：2026-06-29 完成 `AShareTrendStrategy`、时点A股池、时点因子快照、横截面百分位排名、多因子趋势评分、市场状态过滤、独立退出决策和分组收益拆解；时点披露拒绝、时点股票池过滤、市场/趋势过滤、退出逻辑、RawSignal/Explanation和年份/市场/行业拆解测试通过。

### [x] TASK-019——经过校准的预测引擎与不交易机制
- 依赖：TASK-017或TASK-018
- 需求：FR-007、AC-05、AC-12
- 交付：按预测周期独立的基准/模型、概率校准、收益分位数，以及分布外、漂移和样本不足时的不交易结果。
- 验收：T-12通过；提供Brier分数、对数损失、ECE和样本外证据。
- 完成证据：2026-06-29 完成 `ForecastEngine`、`LogisticCalibrator`、预测配置/结果模型、概率方向输出、收益分位数、期望回撤、Brier/LogLoss/ECE校准指标，以及样本不足、分布外、漂移和低置信度不交易机制；READY概率/分位数、不交易诊断概率、校准指标和长度校验测试通过。

### [x] TASK-020——分析报告、当前策略与预期走势面板
- 依赖：TASK-008、TASK-012、TASK-015、TASK-019
- 需求：FR-006至FR-009、FR-020、AC-04至AC-06、AC-10
- 交付：完整`AnalysisReport`、策略面板、概率/区间、操作状态、驱动因素和失效条件。
- 验收：T-12、T-13通过；陈旧数据和分布外状态必须明确显示为不交易。
- 完成证据：2026-06-29 完成 `build_analysis_report()`、`AnalysisPanelState`、策略/预测/操作GUI面板和ViewModel报告应用；可交易报告审计字段、陈旧数据ABSTAIN、分布外模型ABSTAIN、策略/概率/最终操作渲染、陈旧数据可见不交易和旧generation报告丢弃测试通过。

## 阶段5——产品完善

### [x] TASK-021——市场概览、指数与自选列表
- 依赖：TASK-004、TASK-005、TASK-008
- 需求：FR-010、FR-011
- 交付：指数看板、市场广度/成交额/波动状态、分组自选和当前信号。
- 验收：当前选择上下文保持稳定；陈旧状态明确可见。
- 完成证据：2026-06-29 完成 `MarketOverview`、指数快照、市场广度/成交额/波动状态、ViewModel自选分组/排序/信号状态和GUI左侧自选/指数/市场概览渲染；市场广度计算、陈旧指数阻断状态、自选分组信号、当前选择稳定、GUI渲染和指数点击切换测试通过。

### [x] TASK-022——模拟交易经纪与账户
- 依赖：TASK-005、TASK-007、TASK-014至TASK-016、TASK-020
- 需求：FR-015、AC-12
- 交付：模拟订单、成交、持仓、盈亏、信号与实际成交偏差和恢复机制。
- 验收：不存在真实下单路径；T-08、T-09、T-18通过；重启后可以恢复。
- 完成证据：2026-06-29 完成 `SimulationBroker`、`SimulationAccountState`、模拟订单/成交记录、组合入账、盈亏指标、信号-成交偏差、JSON恢复快照和真实下单禁用常量；成交入账、数据陈旧阻断、T+1可卖拒绝、部分成交偏差、状态导出恢复和无真实下单路径测试通过。

### [x] TASK-023——场外基金分析模块
- 依赖：TASK-004至TASK-007、TASK-011、TASK-016
- 需求：FR-016、AC-11
- 交付：正式净值、费用和确认语义，以及周度/月度风险与比较分析。
- 验收：T-06通过；估算净值不能越过正式数据边界。
- 完成证据：2026-06-29 完成 `funds` 场外基金分析模块、申购/赎回确认、费用规则、确认/到账日期、周/月收益、最大回撤、波动率、风险调整收益、费用拖累和基准比较；正式净值确认、截止时间后顺延、赎回现金、估算净值拒绝进入确认/分析和风险比较测试通过。

### [x] TASK-024——知识中心与上下文金融帮助
- 依赖：TASK-008
- 需求：FR-017
- 交付：基于术语表的K线、T+/回转交易、ETF、净值、回撤、期望值和概率校准说明。
- 验收：帮助文本不得承诺收益，并明确区分国际理论与中国市场规则。
- 完成证据：2026-06-30 完成 `knowledge` 知识中心、结构化 `HelpTopic` 安全校验、ViewModel上下文帮助和GUI知识中心页；K线/T+/ETF/净值/回撤/期望值/概率校准条目、禁用收益承诺词、国际理论/中国市场规则区分、搜索排序和GUI筛选渲染测试通过。

### [x] TASK-025——打包、恢复、安全与发布审计
- 依赖：所有MVP任务
- 交付：Windows安装包、数据迁移、凭据管理、异常恢复、可观测性、冒烟测试和发布清单。
- 验收：AC-01至AC-12、NFR-01至NFR-08及完成定义全部通过；不得嵌入凭据。
- 完成证据：2026-06-30 完成 `release` 发布审计模块、PyInstaller Windows one-folder 打包 spec、`.env.example`、凭据排除规则、发布清单、CI发布审计/打包工具烟雾步骤和仓库级嵌入式凭据扫描；AC-01至AC-12、NFR-01至NFR-08、完成定义覆盖校验、恢复/迁移/观测清单、发布CLI、PyInstaller版本烟雾和无凭据扫描测试通过。

## 阶段6——策略决策中枢与盈利验证闭环

### [x] TASK-026——策略决策中枢MVP
- 依赖：TASK-005、TASK-006、TASK-011至TASK-022、TASK-025
- 需求：US-09、FR-021、FR-006至FR-009、FR-013至FR-015、FR-020、C-001、C-006
- 阅读：`docs/exec-plans/completed/0006-strategy-decision-hub.md`、`docs/product-specs/PRODUCT_SPEC.md`、`docs/design/STRATEGY_MODEL_SPEC.md`、`docs/quality/ACCEPTANCE_CRITERIA.md`、`docs/TRACEABILITY.md`
- 核心定位：界面只是行情查看、策略解释和证据复核入口；本任务的核心是把行情、策略、预测、风险、回测、模拟盘和审计串成统一决策报告，用可复现证据回答“当前标的是否值得做、怎么做、做到多少仓位、什么条件下失效”。
- 交付：`DecisionRequest`、`DecisionReport`、`DecisionHub`或等价领域模型；当前标的决策服务；策略/预测/风险/回测/模拟盘证据聚合；GUI当前建议与赚钱证据面板；执行候选状态但无真实下单路径。
- 验收：通过SDA-001至SDA-006；证据不足时必须输出观察或ABSTAIN；不得出现保证盈利文案；不得提交真实订单或保存券商凭据。
- 测试计划：决策报告单元测试、数据/风险/校准/模拟盘门禁故障注入测试、回测证据汇总测试、GUI当前标的建议面板测试、无真实下单路径测试和发布审计回归测试。
- 完成证据：2026-06-30 完成 `decision` 策略决策中枢包、`DecisionRequest`/`DecisionReport`/`DecisionHub`、回测与模拟盘证据摘要、K线研究级决策生成器、GUI“决策证据”面板和联网行情自动决策报告；证据缺失自动降级为观察或ABSTAIN，真实下单路径保持禁用。`ruff format --check .`、`ruff check .`、`mypy src tests` 和 `pytest` 全量通过，测试总数185。

## 阶段7——策略盈利证据与可信验证闭环

### [ ] TASK-027——策略盈利证据、可信回测与模拟盘验证
- 依赖：TASK-013至TASK-022、TASK-026
- 需求：US-09、FR-013至FR-015、FR-020至FR-022、AC-07至AC-12、EPV-001至EPV-006
- 核心定位：下一阶段优先证明“策略到底能不能赚钱、回测是否可信、模拟盘是否能验证”。Electron或前端重构只作为体验优化，不得优先于策略盈利证据、样本外回测、过拟合检查和模拟盘偏差验证。
- 交付：策略验证实验室；固定样本外/滚动前推回测流水线；成本、滑点、涨跌停、停牌和容量压力测试；过拟合与多重检验诊断；策略排行榜/模型卡；模拟盘信号跟踪、成交偏差、漏单/重复信号和稳定性报告；DecisionHub接入真实验证证据。
- 验收：通过EPV-001至EPV-006；任何策略若缺少最终样本外、成本压力、概率校准、风险约束或模拟盘证据，必须保持研究状态或输出ABSTAIN；不得因界面展示好看而提升执行候选等级。
- 测试计划：样本外切分和无泄漏测试、滚动前推回归测试、成本/容量压力测试、参数敏感性测试、模拟盘偏差测试、策略模型卡快照测试、DecisionHub证据门禁集成测试。

## 阶段8——GUI可用性与联网可诊断性

### [x] TASK-028——自选、最近访问、成交量标注与联网诊断修复
- 依赖：TASK-008、TASK-021、TASK-026
- 需求：FR-010、FR-011、FR-021
- 核心定位：修复阻碍用户验证策略证据的界面问题，但不把界面优化置于TASK-027的盈利验证闭环之上。
- 交付：最近访问列表真正从标的选择历史渲染并支持点击；自选列表提供添加当前标的和删除当前标的入口；联网行情成功后自选项补充最新价、涨跌幅和健康状态；成交量柱按涨跌红绿展示并在柱上显示数量；联网失败时说明“收盘后实时价可能停更，但历史K线仍应可取”，帮助区分闭市、网络、代理、防火墙或接口失败。
- 验收：左侧自选和最近访问控件具备可见动作；成交量柱具备数值标注；513300联网实测能区分搜索、K线和quote是否可取；不得改变真实下单禁用边界。
- 完成证据：2026-06-30 完成 `RecentSecurityState`、ViewModel最近访问刷新、自选按钮与左侧列表渲染、watchlist行情快照、成交量柱数值标注和联网失败提示。联网实测 `513300` 可从东方财富返回1条搜索结果、31条日K和实时quote，说明15:00后不是历史K线不可取的原因；新增GUI测试覆盖自选按钮与最近访问点击。`ruff format --check .`、`ruff check .`、`mypy src tests`、`pytest` 188项和 `python -m china_quant_platform.release.audit` 均通过。

### [x] TASK-029——代码回车兜底与联网错误弹窗
- 依赖：TASK-008、TASK-028
- 需求：FR-001、FR-003、FR-004、FR-021
- 核心定位：修复用户输入 `513300` 后联网搜索断开导致无法进入行情加载的问题；搜索接口只应辅助识别名称，不应成为6位证券代码拉取K线的单点阻断。
- 交付：输入框回车时立即同步处理当前文本，不再等待防抖定时器；6位代码、本地市场前缀代码和交易所前缀代码生成本地兜底 `SecurityRef`；联网搜索断开但已有兜底候选或已选中标的时不再阻断数据健康；东方财富HTTP请求增加短重试并捕获服务端主动断开，K线请求补充必需 `ut` 参数；东方财富日K或quote失败时降级到Yahoo chart日线/quote；顶部红色长错误改为短状态，完整原因通过非阻塞弹窗展示。
- 验收：在联网搜索抛出 `Remote end closed connection without response` 的情况下，输入 `513300` 并回车仍会选择 `SSE:513300`、请求K线和quote，并在行情成功后显示健康状态；长错误不得挤压输入框；东方财富历史K线或quote临时断开时，默认日线图可由备用源返回。
- 完成证据：2026-06-30 完成 `test_enter_on_code_loads_chart_when_online_search_disconnects`、`test_online_failure_uses_short_banner_and_popup`、东方财富K线/quote到Yahoo备用源单元测试；真实联网复测 `513300` 当前搜索接口返回0，但日K返回31条、quote返回2.704，二者均由Yahoo备用源补齐。`ruff format --check .`、`ruff check .`、`mypy src tests`、`pytest` 192项和 `python -m china_quant_platform.release.audit` 均通过。

### [x] TASK-030——同花顺优先的数据源路由
- 依赖：TASK-003、TASK-005、TASK-029
- 需求：FR-001、FR-003、FR-004、FR-020
- 核心定位：默认优先使用同花顺 iFinD/QuantAPI 数据源；同花顺未配置或访问不通时，自动降级到东方财富/Yahoo兜底，避免单一公开接口不稳定阻断策略验证。
- 交付：`TonghuashunIfindMarketDataProvider`、`TonghuashunIfindConfig`、`MultiSourceMarketDataProvider`、默认 provider 工厂、`.env.example` 同花顺配置项、GUI 默认多源启动链路。
- 验收：有 `CQP_THS_IFIND_REFRESH_TOKEN` 时 provider 链首位为 `tonghuashun_ifind`；无 token 时自动跳过同花顺；同花顺请求失败时路由到下一数据源；不得提交真实 token。
- 完成证据：2026-06-30 完成同花顺 iFinD HTTP适配器、token/.env配置读取、多源路由和默认工厂；新增 `test_tonghuashun_provider.py` 与 `test_multi_source_provider.py` 覆盖配置、代码识别、quote/K线映射、失败切换和默认优先级；`ruff format --check .`、`ruff check .`、`mypy src tests`、`pytest` 202项、`python -m china_quant_platform.release.audit`、PyInstaller打包、exe版本和GUI启动烟雾均通过。

### [x] TASK-031——分钟K线联网兜底修复
- 依赖：TASK-029、TASK-030
- 需求：FR-001、FR-003、FR-004、FR-021
- 核心定位：修复 `513300` 在 `30分` 等分钟周期下东方财富K线 SSL 握手超时导致图表无数据的问题；分钟线不得因为单一公开接口失败而阻断策略查看。
- 交付：Yahoo chart 分钟/日/周/月 K 线统一兜底；1分/5分/15分/30分/60分周期映射；分钟线超长范围自动缩到 Yahoo 可返回窗口；东方财富分钟线失败回归测试。
- 验收：东方财富分钟K线抛出 `ssl handshake timed out` 时，`SSE:513300` 的 `30分` 请求仍能返回 Yahoo K 线；数据源失败弹窗不应导致图表保持空白；不得引入真实账号或 token 依赖。
- 完成证据：2026-06-30 完成 `test_eastmoney_minute_klines_fall_back_to_yahoo`，真实联网诊断 `SSE:513300` / `30分` 返回174根 Yahoo K线；`ruff format --check .`、`ruff check .`、`mypy src tests`、`pytest` 203项均通过。
