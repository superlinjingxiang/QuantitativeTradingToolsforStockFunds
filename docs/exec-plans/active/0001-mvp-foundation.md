# MVP基础能力执行计划

## 目的和用户可见结果

建立可复现仓库、标准领域契约、假数据供应商、证券搜索、数据质量门禁和按日期生效的规则引擎。完成后，开发者无需GUI或真实供应商凭据，即可安装项目、搜索夹具证券、加载确定性的夹具K线和行情、观察数据健康失败，并解析指定日期的交易规则。

## 背景与仓库定位

当前仓库仅包含规格。开始前阅读 `AGENTS.md`、`TASKS.md`、`docs/architecture/ARCHITECTURE.md`、`docs/design/DATA_CONTRACTS.md`、`docs/domain/MARKET_RULES.md` 和 `docs/quality/TEST_MATRIX.md`。

## 范围

### 范围内

TASK-001至TASK-007。

### 范围外

GUI、生产供应商凭据、策略、预测、模拟交易和真实交易。

## 需求编号与验收编号

FR-001、FR-003、FR-004、FR-020；AC-01、AC-06、AC-09、AC-10、AC-11；NFR-06、NFR-08；T-02至T-06、T-09、T-10、T-15、T-16。

## 进度

- [x] 2026-06-28 12:12Z — 仓库搭建和命令可确定复现；TASK-001已完成。
- [x] 2026-06-28 12:34Z — 标准领域模型、类型化错误和Schema双向转换；TASK-002已完成。
- [x] 2026-06-28 12:45Z — 数据供应商协议、能力声明、确定性假供应商、取消与限流行为；TASK-003已完成。
- [x] 2026-06-29 02:55Z — 证券主数据、时点状态、本地模糊搜索、最近搜索和P95性能夹具；TASK-004已完成。
- [x] 2026-06-29 03:35Z — 历史/实时数据网关、Parquet分区缓存、增量补缺和实时订阅状态；TASK-005已完成。
- [x] 2026-06-29 04:10Z — 数据质量门禁、结构化阻断报告和跨源Quote对账；TASK-006已完成。
- [x] 2026-06-29 04:45Z — 按日期生效的中国市场规则解析、订单校验和基金语义；TASK-007已完成。

## 意外情况与发现

- 2026-06-28 — 工作区根目录下存在空 `.git/` 目录但不是可识别Git仓库；TASK-001不初始化或修改Git元数据。
- 2026-06-28 — 系统 `python` 不在PATH，`py -3.11` 记录存在但启动失败；Codex bundled Python 3.12.13可用，因此项目固定Python 3.12。
- 2026-06-28 — `uv` 默认用户缓存目录存在权限问题；本机验证使用 `UV_CACHE_DIR=.uv-cache`，并将 `.uv-cache/` 忽略。
- 2026-06-28 — `AnalysisReport` Schema 仅对概率字段做0到1范围约束；领域模型额外强制 `up + flat + down == 1`，以满足数据契约中“概率归一化”不变量。
- 2026-06-28 — 场外基金正式净值和估算净值实现为两个不同模型：`FundNav` 与 `EstimatedFundNav`，防止估算净值进入正式净值回测路径。
- 2026-06-28 — TASK-003的确定性假供应商只生成小型内存fixture，不写入Parquet/SQLite，也不实现本地搜索索引；这些保留给TASK-004和TASK-005。
- 2026-06-29 — TASK-004的搜索索引为内存实现，覆盖候选返回和性能基准；SQLite/持久化最近搜索仍留给后续存储任务。
- 2026-06-29 — `pyarrow.parquet.read_table()` 会识别Hive风格分区路径中的同名字段；TASK-005按单个分区文件使用 `ParquetFile(...).read()`，避免路径分区字段与文件字段合并冲突。

## 决策日志

- 2026-06-28 — 接受ADR-004：使用Python 3.12、`uv`、`pyproject.toml`和 `uv.lock`；首轮加入PySide6依赖但不实现GUI外壳。
- 2026-06-28 — TASK-001仅建立基础工程与验证闭环；不实现领域模型、数据供应商、规则引擎、策略、回测或GUI窗口。
- 2026-06-28 — 接受ADR-005：使用Pydantic v2实现不可变领域契约模型，并把 `pydantic` 作为显式生产依赖。
- 2026-06-28 — TASK-002实现领域模型与错误分类；不实现供应商协议、假供应商、搜索索引、缓存或规则解析。
- 2026-06-28 — 接受ADR-006：在 `data` 层使用协议和确定性假供应商验证供应商边界，缺能力使用类型化 `DataUnavailable`。
- 2026-06-28 — TASK-003实现供应商协议、能力声明、假供应商、取消和限流；不实现证券主数据索引、数据缓存或真实供应商接入。
- 2026-06-29 — 接受ADR-007：首版证券主数据使用内存索引，采用归一化精确/前缀/包含/子序列评分。
- 2026-06-29 — TASK-004实现证券主数据和本地搜索；不实现GUI搜索框、原子化证券切换、远端补充或持久化存储。
- 2026-06-29 — 接受ADR-008：历史K线缓存使用 `pyarrow` 写入Parquet分区，并由数据网关统一协调增量补缺和实时状态。
- 2026-06-29 — TASK-005实现历史/实时数据网关与缓存；不实现独立数据质量服务、交易日历、GUI图表或真实供应商接入。
- 2026-06-29 — 接受ADR-009：数据质量门禁输出结构化阻断报告，并用类型化错误和 `DataHealth` 对上层暴露。
- 2026-06-29 — TASK-006实现数据质量服务、阻断等级和基础跨源对账；不实现完整交易日历、公司行为复权核对或多供应商真实接入。
- 2026-06-29 — 接受ADR-010：首版市场规则使用内存仓库按生效日期解析，缺失或冲突规则以 `RuleMissing` 失败。
- 2026-06-29 — TASK-007实现规则解析和基础订单语义；不实现真实规则数据库、公司行为记账或完整交易日历。

## 架构与接口

遵循 `docs/architecture/ARCHITECTURE.md`。领域模块不得导入GUI、供应商SDK、HTTP客户端或具体数据库。外部I/O必须通过协议实现。

## 里程碑

### 里程碑1——仓库和领域契约

实现TASK-001和TASK-002，并完成测试和Schema校验。

状态：TASK-001和TASK-002已完成。进入TASK-003前无需补充仓库骨架或基础领域契约。

### 里程碑2——供应商抽象与证券主数据

使用确定性夹具实现TASK-003和TASK-004。

状态：TASK-003和TASK-004已完成。

### 里程碑3——数据缓存与质量门禁

实现TASK-005和TASK-006，包括取消和故障注入。

状态：TASK-005和TASK-006已完成。

### 里程碑4——规则引擎

实现TASK-007，完成生效日期边界测试和关闭式失败行为。

状态：TASK-007已完成。

## 具体实施步骤

- TASK-001已创建 `pyproject.toml`、`.python-version`、`.gitignore`、`.github/workflows/ci.yml`、`uv.lock`。
- 已创建 `src/china_quant_platform/` 及架构要求的 `app`、`ui`、`domain`、`data`、`rules`、`indicators`、`factors`、`strategies`、`forecasting`、`backtest`、`risk`、`portfolio`、`simulation`、`reporting`、`infrastructure` 子包。
- 已提供最小公共接口：`__version__`、`python -m china_quant_platform --version`、`AppSettings`、`RuntimeContext`、`bootstrap_runtime()`、`configure_logging()`。
- 已创建 `tests/unit`、`tests/integration`、`tests/regression`、`tests/gui`、`tests/fixtures`，并加入导入、运行时、PySide6和机器可读契约冒烟测试。
- TASK-002已创建 `domain` 枚举、ID类型别名、Schema转换基类、标准证券/行情/K线/基金净值/公司行为/数据健康/分析报告/回测配置/交易规则模型，以及类型化错误层级。
- `AnalysisReport` 领域模型强制可交易报告具备未阻断数据、来源版本、正负驱动、失效/退出条件和归一化概率；`ABSTAIN` 强制包含有类型原因。
- TASK-003已创建 `MarketDataProvider` 协议、`BarsRequest`、`CorporateActionRequest`、`FundNavRequest`、`ProviderCapabilities`、`ProviderCapability`、`AsyncRateLimiter` 和 `DeterministicFakeMarketDataProvider`。
- 假供应商当前覆盖证券搜索、实时Quote、日线K线、实时订阅、公司行为和正式基金净值；分钟K线能力默认未开启，调用时以类型化缺能力错误失败。
- TASK-004已创建 `SecurityMasterRecord`、`SecuritySearchResult`、`RecentSecuritySelection` 和 `SecurityMasterService`，支持时点状态解析、代码/名称/别名搜索、子序列模糊匹配、非活跃过滤和最近访问LRU。
- TASK-005已创建 `HistoricalBarCache`、`BarCacheAppendResult`、`MarketDataGateway`、`RealtimeSubscriptionState` 和 `RealtimeConnectionStatus`，支持K线Parquet分区、重复记录防护、坏分区类型化错误、缺口补齐、陈旧Quote健康状态、订阅取消和断线重连。
- TASK-006已创建 `DataQualityService`、`DataQualityPolicy`、`DataQualityIssue`、`DataQualityReport` 和阻断等级枚举，支持新鲜度、完整性、一致性、授权检查、跨源Quote对账和类型化阻断错误。
- TASK-007已创建 `InMemoryRuleRepository`、`MarketRuleEngine`、`OrderSide`、`PriceLimitBand`、`RuleValidationResult` 和 `FeeBreakdown`，支持规则生效日期解析、证券专属优先、订单数量/价格校验、涨跌停、停牌、T+可卖数量、费用、基金正式净值语义和披露时间可见性。

## 验证与验收

至少运行上述关联的单元、契约、集成和确定性回归套件。演示非法/陈旧数据会阻止可生成信号的结果，缺失规则会关闭式失败。

TASK-001验证证据（2026-06-28）：

- `uv lock` 生成 `uv.lock`。
- `uv sync --all-extras --dev` 成功同步依赖。
- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，9个测试通过。
- `uv run python -m china_quant_platform --version` 输出 `0.1.0`。

TASK-002验证证据（2026-06-28）：

- `uv lock` 和 `uv sync --all-extras --dev` 成功。
- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，36个测试通过。
- 覆盖Schema往返、非法概率、naive时间戳、可交易报告来源信息、数据健康阻断、正式/估算基金净值隔离和错误分类元数据。

TASK-003验证证据（2026-06-28）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，46个测试通过。
- 覆盖供应商协议运行时符合性、确定性搜索/Quote/K线/净值、实时订阅、缺能力错误、异步取消、限流等待和领域层不依赖供应商层。

TASK-004验证证据（2026-06-29）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，54个测试通过。
- 覆盖T-10：代码、名称和别名搜索返回去重后的有类型候选。
- 覆盖NFR-01：2000证券夹具上本地搜索P95小于300毫秒。

TASK-005验证证据（2026-06-29）：

- `uv lock` 和 `uv sync --all-extras --dev` 成功，`pyarrow` 已纳入 `uv.lock`。
- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest tests/unit/test_bar_cache.py tests/integration/test_market_data_gateway.py` 通过，9个TASK-005相关测试通过。
- 覆盖Parquet分区读写、重复时间戳、损坏OHLC、幂等追加、缺口计算、增量补缺、陈旧Quote阻断、订阅取消和断线重连。

TASK-006验证证据（2026-06-29）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，74个测试通过。
- 覆盖T-08/T-16：重复K线、非法OHLC、缺失K线、陈旧Quote、缺失字段、未授权供应商、跨源Quote不一致、健康数据放行和被阻断数据拒绝可交易报告。

TASK-007验证证据（2026-06-29）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，85个测试通过。
- 覆盖T-02至T-06、T-15：有效期边界、证券专属规则优先、缺规则关闭式失败、T+可卖数量、涨停无流动性不默认成交、停牌阻断、手数/最小价位、费用、场外基金估算净值隔离和披露前不可见。

## 可复现性、幂等性与恢复

夹具生成必须确定。数据库/缓存初始化和迁移必须可安全重复执行。测试不得依赖网络或秘密凭据。

## 风险与缓解措施

- 时间戳含义模糊：分别定义源时间、时点时间、接收时间和交易日期。
- 规则过度泛化：按资产、具体证券和日期解析，并测试边界。
- 过早绑定供应商：先使用假供应商，再接入真实供应商。
- Schema漂移：使用标准契约验证适配器。

## 产物与备注

- TASK-001产物：可复现Python工程骨架、运行时配置/日志骨架、CI骨架、锁文件和基础测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-004。
- TASK-002产物：标准领域模型、类型化错误、契约往返测试和领域不变量测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-005。
- TASK-003产物：数据供应商协议、请求模型、能力声明、异步限流器、确定性假供应商和供应商契约测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-006。
- TASK-004产物：证券主数据内存服务、本地模糊搜索、时点状态解析、最近访问列表和性能夹具。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-007。
- TASK-005产物：历史K线Parquet缓存、市场数据网关、实时订阅状态和增量补缺测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-008。
- TASK-006产物：数据质量门禁、结构化质量报告、阻断错误映射、跨源Quote对账和信号阻断测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-009。
- TASK-007产物：内存市场规则仓库、按生效日期解析的规则引擎、订单校验、费用计算和基金语义测试。
- 新增决策：`docs/DECISIONS.md` 中的 ADR-010。
- `.uv-bootstrap/` 是本机安装 `uv` 的临时引导环境，已忽略，不属于项目交付物。

## 结果与复盘

TASK-001至TASK-007已完成，基础仓库、领域契约、供应商抽象、证券主数据、历史/实时数据网关、数据质量门禁和中国市场规则引擎均具备可运行测试。进入GUI阶段前仍需注意：真实供应商、真实规则来源、完整交易日历、公司行为记账、数据库迁移和生产凭据管理仍未实现，后续任务不得把当前内存fixture误认为生产数据。
