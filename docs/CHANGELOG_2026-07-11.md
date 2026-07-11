# 近期改动说明（2026-07-11）

## 这次改动解决什么问题

本轮改动把项目从“Electron 原生 HTML/JS + Python 标准库 HTTP 服务”的形态，升级为“Vue 3 前端 + FastAPI 本地后端 + Electron 桌面壳”。核心策略、预测、回测、荐股和手动账户评估仍由 Python 领域服务负责，前端只负责展示和交互。

目标是让项目更容易维护，也让重复打开标的、行情源暂时失败和桌面首次加载时的体验更稳定。当前版本仍是研究和模拟工具，不执行真实下单。

## 主要变化

### 1. FastAPI 后端兼容层

- 新增 `src/china_quant_platform/api/`，提供 FastAPI app factory、请求模型、错误响应和 OpenAPI 文档。
- 保留主要接口路径：`/api/health`、`/api/search`、`/api/analyze`、`/api/recommendations`、`/api/market-overview`。
- FastAPI 只做 HTTP 适配和参数校验，继续调用原有 `ElectronBackendService`，没有复制一套策略算法。
- 本地服务默认只监听 `127.0.0.1`，可以通过 `/docs` 查看接口文档。

### 2. Redis 优先、内存降级缓存

- 新增统一缓存抽象和 Redis/内存两种后端。
- Redis 可用时缓存短期 API 结果；Redis 未启动时自动使用进程内缓存，项目仍然可以一键启动。
- 健康状态、报价、搜索、分析和荐股池使用不同 TTL；历史 K 线仍由本地 Parquet 缓存负责。
- 数据源失败但存在上一次成功结果时，返回陈旧结果并标记 `STALE`/`DEGRADED`，前端保留可见数据，但不把陈旧数据当成新的正式交易信号。
- 缓存键包含接口、标的、周期、范围、复权、策略模式、交易次数、账户摘要和版本信息，避免不同分析条件互相污染。

### 3. Vue 3 工作台和 Electron 集成

- 新增 `frontend/`，使用 Vue 3、TypeScript、Vite、Pinia、Vue Router 和 ECharts。
- Electron 默认加载 Vue 构建产物；旧版 renderer 通过 `CQP_FRONTEND=legacy` 保留回退入口，PySide6 入口也继续保留。
- 首次打开先读取本地最近一次成功分析，再后台请求最新数据；请求代次和 `AbortController` 防止旧请求覆盖新标的。
- 页面支持自动刷新、失败保留上一次数据、整体纵向滚动、深色/浅色主题和图表层切换。
- 图表支持行情价格、涨跌幅、成交量、MA、回测信号和预测区间；预测区间使用独立颜色和图层，和实际行情日期轴对齐。

### 4. 原有业务功能保持并接通

- 短线/长线策略切换、交易次数、回测曲线、预测走势和右侧四块决策面板继续使用同一套 Python 结果。
- 荐股池保留 A 股账户可买范围、T+0/T+1 标签、评分降序、点击候选跳转行情和失败数据说明。
- 手动账户输入继续按当前策略评估成本价、数量、仓位、浮动盈亏和账户建议，不创建第二套策略。
- 指数/市场概览支持自动刷新和历史数据兜底。
- 同花顺优先的数据源路由和其他数据源兜底逻辑保持不变；真实下单路径仍被禁止。

### 5. 可读性和稳定性修复

- 价格卡片增加上涨/下跌箭头，并保持中国市场上涨红色、下跌绿色语义。
- 右侧策略、预测、操作风险、决策证据面板改为紧凑信息卡，中文字段更容易阅读。
- 浅色主题重新调整对比度；图表在浅色主题下保留深色绘图区，避免坐标、网格和提示文字看不清。
- Electron 启动脚本增加构建检查和 FastAPI 子进程启动流程，修复生产页面黑屏的资源路径问题。

## 验证结果

本轮迁移完成后已执行：

- Python 全量回归：`255 passed`。
- Ruff 格式检查、Ruff lint、mypy：通过。
- FastAPI TestClient、健康接口和 OpenAPI 启动冒烟：通过。
- Vue/TypeScript 构建：通过。
- Vitest：通过。
- Playwright：`2 passed`，覆盖基础工作台加载、缓存数据展示、主题切换、图表层、账户输入、自选和荐股联动。
- Electron 生产页面启动冒烟：通过。

## 运行方式

在仓库根目录执行：

```powershell
.\start_electron.bat
```

开发前端和 Electron：

```powershell
npm.cmd install
npm.cmd run electron:dev
```

单独启动 FastAPI：

```powershell
.\.venv\Scripts\python.exe -m china_quant_platform.api --host 127.0.0.1 --port 8765
```

Redis 是可选项。需要启用 Redis 时设置 `CQP_REDIS_URL`；不设置或 Redis 不可用时，程序自动降级到内存缓存。

## 当前边界和后续工作

- 缓存解决重复加载和短时数据源失败，不等于实时行情保证；数据健康状态仍必须先通过门禁。
- 预测和回测结果是研究证据，不代表未来收益，也不能替代模拟盘验证。
- 目前仍不连接券商账户、不读取真实持仓、不执行真实 API 下单。
- 后续可以继续做 ECharts 分包、真实 Redis 压力测试、模拟盘偏差报告和更完整的多资产样本外验证。

相关设计记录：

- `docs/DECISIONS.md`：ADR-040 至 ADR-042。
- `docs/architecture/ARCHITECTURE.md`：当前 FastAPI/Vue/Electron 架构。
- `docs/design/CACHE_AND_ELECTRON_TRANSITION.md`：缓存、陈旧数据和 Electron 边界。
- `docs/exec-plans/active/0008-fastapi-vue-redis-refactor.md`：本轮重构执行记录。
