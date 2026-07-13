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

最新工程进度快照见：`docs/PROJECT_STATUS_2026-07-02.md`。

2026年7月11日已完成 FastAPI + Vue + Redis 兼容迁移：Vue 成为 Electron 默认前端，FastAPI 复用现有 Python 业务服务，Redis 不可用时自动降级到内存缓存。近期改动、验证结果、运行边界和后续风险见：`docs/CHANGELOG_2026-07-11.md`。

TASK-001 至 TASK-025 已完成：当前仓库包含可复现 Python 工程骨架、`src/` 包结构、测试目录、配置/日志启动骨架、CI 骨架、`.gitignore`、`uv.lock`、标准领域模型、类型化错误、数据供应商协议、确定性假供应商、证券主数据、本地搜索索引、历史K线Parquet缓存、增量补缺网关、实时订阅状态、数据质量门禁、按生效日期解析的中国市场规则引擎、PySide6应用外壳、GUI搜索/原子化证券切换、实时/历史图表工作区、确定性指标/因子注册表、策略接口/解释模型、事件驱动回测内核、执行/成本/流动性/公司行为模型、组合/风险引擎、回测报告/固定回归夹具、ETF中期轮动研究基准策略、A股多因子趋势研究基准策略、经过校准的概率预测/不交易引擎、`AnalysisReport` 合成和GUI策略/预期走势/操作风险面板、市场概览/指数/自选列表状态、无真实下单路径的模拟经纪与可恢复账户状态、场外基金正式净值确认和风险比较分析、区分国际理论和中国市场规则的知识中心/上下文帮助，以及Windows PyInstaller打包入口、发布清单、恢复/迁移/观测审计和嵌入式凭据扫描。

## 策略验证状态

2026年7月13日完成盈利验证策略 V5 阶段改造：保留 V4 的 20% 目标波动、7.5% 止损和数据快照，并为 A 股个股增加经过开发折筛选的 3%/20% 反追涨约束。代码改动见 `docs/CHANGELOG_2026-07-13.md`，V5 方法与真实三组十标的结果见 `docs/research/SHORT_TERM_STRATEGY_VALIDATION_V5_2026-07-13.md`，V4 风险暴露记录保留在 `docs/research/SHORT_TERM_STRATEGY_VALIDATION_V4_2026-07-13.md`。

当前十 ETF 和混合十标的实验都只有 2/10 PASS；十 A 股虽然平均最终收益为 5.71%，但仍为 0/10 PASS，不代表保证盈利。可使用以下命令复现：

    .\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe stock10

    .\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe etf10

    .\.venv\Scripts\python.exe -m china_quant_platform.strategies.lab --strategy-mode short_term --horizon 1m --max-trades 12 --history-years 7 --universe mixed10

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

启动 Electron 桌面外壳：

```powershell
.\start_electron.bat
```

Electron 只负责 UI 和交互；行情、策略、回测、决策门禁仍由本地 Python 后端计算。首次运行会通过 `npm.cmd install` 安装 Electron 依赖。

当前现代化入口使用 Vue 3/Vite 前端和 FastAPI 后端：

```powershell
npm.cmd install
npm.cmd run build
.\start_electron.bat
```

开发时可使用：

```powershell
npm.cmd run electron:dev
```

FastAPI本地接口默认监听随机本地端口（Electron启动时注入），直接调试后端可运行：

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.api --host 127.0.0.1 --port 8765
```

接口文档位于 `/docs`。Redis通过 `CQP_REDIS_URL` 配置；Redis未启动时自动使用内存缓存，历史K线仍使用项目内Parquet缓存。旧版原生Electron界面可用 `CQP_FRONTEND=legacy` 回退，PySide6入口继续由 `start_gui.bat` 提供。

## 行情数据源

GUI 默认使用多数据源路由：

1. 同花顺 iFinD / QuantAPI（已配置 `CQP_THS_IFIND_REFRESH_TOKEN` 时启用）
2. 东方财富公开接口
3. Yahoo chart 日线/quote 备用源

同花顺 token 不提交到仓库。可在本机环境变量或本地忽略的 `.env` 中配置：

```powershell
$env:CQP_THS_IFIND_REFRESH_TOKEN = "你的refresh_token"
```

`refresh_token` 获取路径：同花顺超级命令客户端的“工具 -> refresh_token 查询”，或网页版超级命令的“账号详情”。是否收费取决于你的同花顺 iFinD/QuantAPI 账号权限；普通同花顺 App 账号不等同于已开通数据 API。如果未配置 token，程序会自动跳过同花顺并继续使用后备源。

本机如需避开用户目录缓存权限问题，可设置项目内缓存：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
```

## ai-hedge-fund 独立研究入口

本项目保留现有 `strategies.profit_validation` 盈利验证策略作为主策略链路。`virattt/ai-hedge-fund` 只作为可选研究代理入口接入，不覆盖主策略、不提升真实交易候选等级。

先单独 clone 并安装外部项目：

```powershell
git clone https://github.com/virattt/ai-hedge-fund.git E:\股票基金量化工程\ai-hedge-fund
cd E:\股票基金量化工程\ai-hedge-fund
poetry install
```

配置路径和外部项目需要的 key：

```powershell
$env:CHINA_QUANT_AI_HEDGE_FUND_PATH = "E:\股票基金量化工程\ai-hedge-fund"
$env:FINANCIAL_DATASETS_API_KEY = "你的Financial Datasets key"
$env:OPENAI_API_KEY = "你的OpenAI或其他LLM key"
```

先 dry-run 检查命令，不实际调用外部代理：

```powershell
uv run python -m china_quant_platform.ai_hedge_fund --ticker AAPL --dry-run
```

真正运行时可指定外部仓库使用的 Python：

```powershell
uv run python -m china_quant_platform.ai_hedge_fund `
  --ticker AAPL,MSFT `
  --start-date 2026-01-01 `
  --end-date 2026-03-01 `
  --python "E:\股票基金量化工程\ai-hedge-fund\.venv\Scripts\python.exe"
```

该入口主要面向 `ai-hedge-fund` 支持的美股符号和它自己的数据源。A股/ETF主流程继续使用本项目行情、回测、盈利验证和DecisionHub门禁。
