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
- [ ] 标准契约和Schema可双向转换。
- [ ] 假供应商通过契约测试。
- [ ] 证券主数据/搜索通过正确性和性能夹具。
- [ ] 历史/实时缓存与数据质量门禁通过故障测试。
- [ ] 按日期生效的规则通过边界测试。

## 意外情况与发现

- 2026-06-28 — 工作区根目录下存在空 `.git/` 目录但不是可识别Git仓库；TASK-001不初始化或修改Git元数据。
- 2026-06-28 — 系统 `python` 不在PATH，`py -3.11` 记录存在但启动失败；Codex bundled Python 3.12.13可用，因此项目固定Python 3.12。
- 2026-06-28 — `uv` 默认用户缓存目录存在权限问题；本机验证使用 `UV_CACHE_DIR=.uv-cache`，并将 `.uv-cache/` 忽略。

## 决策日志

- 2026-06-28 — 接受ADR-004：使用Python 3.12、`uv`、`pyproject.toml`和 `uv.lock`；首轮加入PySide6依赖但不实现GUI外壳。
- 2026-06-28 — TASK-001仅建立基础工程与验证闭环；不实现领域模型、数据供应商、规则引擎、策略、回测或GUI窗口。

## 架构与接口

遵循 `docs/architecture/ARCHITECTURE.md`。领域模块不得导入GUI、供应商SDK、HTTP客户端或具体数据库。外部I/O必须通过协议实现。

## 里程碑

### 里程碑1——仓库和领域契约

实现TASK-001和TASK-002，并完成测试和Schema校验。

### 里程碑2——供应商抽象与证券主数据

使用确定性夹具实现TASK-003和TASK-004。

### 里程碑3——数据缓存与质量门禁

实现TASK-005和TASK-006，包括取消和故障注入。

### 里程碑4——规则引擎

实现TASK-007，完成生效日期边界测试和关闭式失败行为。

## 具体实施步骤

- TASK-001已创建 `pyproject.toml`、`.python-version`、`.gitignore`、`.github/workflows/ci.yml`、`uv.lock`。
- 已创建 `src/china_quant_platform/` 及架构要求的 `app`、`ui`、`domain`、`data`、`rules`、`indicators`、`factors`、`strategies`、`forecasting`、`backtest`、`risk`、`portfolio`、`simulation`、`reporting`、`infrastructure` 子包。
- 已提供最小公共接口：`__version__`、`python -m china_quant_platform --version`、`AppSettings`、`RuntimeContext`、`bootstrap_runtime()`、`configure_logging()`。
- 已创建 `tests/unit`、`tests/integration`、`tests/regression`、`tests/gui`、`tests/fixtures`，并加入导入、运行时、PySide6和机器可读契约冒烟测试。

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
- `.uv-bootstrap/` 是本机安装 `uv` 的临时引导环境，已忽略，不属于项目交付物。

## 结果与复盘

所有里程碑完成后填写，并记录进入GUI工作前的剩余缺口。
