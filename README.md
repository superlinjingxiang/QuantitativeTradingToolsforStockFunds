# 中国股票与基金量化分析平台——Codex 工程规格包

本仓库文档包将原始产品需求文档（PRD）和技术需求规格（SRS）重构为适合 Codex 与工程人员协同开发的仓库式规格。

> 说明：面向人阅读的内容采用中文；类名、接口名、状态枚举、需求编号、文件路径和 JSON/YAML 字段名保留英文，以保证代码、Schema和追踪关系稳定。

## 为什么采用这种结构

- `AGENTS.md` 保持简短，作为Codex的项目指令和文档导航入口。
- `docs/` 是受版本控制的需求与设计事实源。
- `PLANS.md` 规定复杂任务的执行计划（ExecPlan）如何编写和维护。
- `TASKS.md` 将MVP拆分为有依赖关系、可独立验证的工作项。
- `spec/requirements.yaml` 和 JSON Schema 提供机器可读的需求与数据契约。

## 开始使用

1. 阅读 `AGENTS.md`。
2. 打开 `TASKS.md`，选择一个依赖已完成的任务。
3. 根据 `docs/index.md` 阅读该任务引用的文档。
4. 复杂任务应根据 `PLANS.md` 创建执行计划，或更新 `docs/exec-plans/active/0001-mvp-foundation.md`。
5. 实现、测试并更新追踪矩阵后，才能将任务标记为完成。

## 建议给 Codex 的第一条指令

```text
阅读 AGENTS.md、README.md、TASKS.md、docs/index.md，以及 TASK-001 中引用的所有相关文档。
如果 PLANS.md 规定需要执行计划，请创建或更新对应的 ExecPlan。
只实施 TASK-001，不要开始后续任务。
运行该任务要求的检查，更新需求追踪信息，并总结修改文件、检查结果和剩余风险。
```

## 文档导航

- 产品需求：`docs/product-specs/PRODUCT_SPEC.md`
- 工程与技术需求：`docs/technical/TECHNICAL_SPEC.md`
- 架构设计：`docs/architecture/ARCHITECTURE.md`
- GUI规格：`docs/product-specs/GUI_SPEC.md`
- 国际金融理论：`docs/domain/FINANCIAL_THEORY.md`
- 中国市场规则：`docs/domain/MARKET_RULES.md`
- 数据契约：`docs/design/DATA_CONTRACTS.md`
- 策略与模型：`docs/design/STRATEGY_MODEL_SPEC.md`
- 回测规格：`docs/design/BACKTEST_SPEC.md`
- 验收条件：`docs/quality/ACCEPTANCE_CRITERIA.md`
- 测试矩阵：`docs/quality/TEST_MATRIX.md`
- 需求追踪：`docs/TRACEABILITY.md`

## 当前状态

规格基线：V1.0，日期为2026年6月28日。

TASK-001 至 TASK-017 已完成：当前仓库包含可复现 Python 工程骨架、`src/` 包结构、测试目录、配置/日志启动骨架、CI 骨架、`.gitignore`、`uv.lock`、标准领域模型、类型化错误、数据供应商协议、确定性假供应商、证券主数据、本地搜索索引、历史K线Parquet缓存、增量补缺网关、实时订阅状态、数据质量门禁、按生效日期解析的中国市场规则引擎、PySide6应用外壳、GUI搜索/原子化证券切换、实时/历史图表工作区、确定性指标/因子注册表、策略接口/解释模型、事件驱动回测内核、执行/成本/流动性/公司行为模型、组合/风险引擎、回测报告/固定回归夹具和ETF中期轮动研究基准策略。后续仍需按 `TASKS.md` 顺序实现A股多因子、预测、解释面板和模拟账户等业务能力。

## 开发环境

- Python：`3.12`
- 依赖管理：`uv`
- 包名：`china-quant-platform`
- 导入名：`china_quant_platform`

首次安装：

```powershell
uv sync --all-extras --dev
```

如果当前机器尚未把 `uv` 放入 `PATH`，可以先安装 `uv`，或使用本机开发时创建的项目内 bootstrap 可执行文件：

```powershell
.\.uv-bootstrap\Scripts\uv.exe sync --all-extras --dev
```

`.uv-bootstrap/` 仅用于本机引导，已被 `.gitignore` 忽略，不属于正式交付物。

## 检查命令

```powershell
uv lock
uv sync --all-extras --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m china_quant_platform --version
```

启动桌面外壳：

```powershell
uv run python -m china_quant_platform --gui
```

本机如需避开用户目录缓存权限问题，可设置项目内缓存：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
```
