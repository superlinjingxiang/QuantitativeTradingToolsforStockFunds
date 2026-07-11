# FastAPI、Vue与Redis现代化重构

## 目的和用户可见结果

默认桌面入口由Vue渲染，FastAPI提供本地后端API；原有行情、策略、预测、回测、荐股、手动账户评估结果保持兼容。重复打开标的优先读取缓存，数据源失败时保留上次结果并明确标记陈旧状态。

## 背景与仓库定位

当前项目使用Electron + 原生HTML/JS + Python `ThreadingHTTPServer`。核心业务位于`src/china_quant_platform`，历史K线已有Parquet缓存，策略和回测不可在前端重写。

## 范围

### 范围内

- FastAPI兼容 `/api/health`、`/api/search`、`/api/analyze`、`/api/recommendations`。
- Redis优先、内存降级的短期API缓存和陈旧回退。
- Vue 3/Vite/Pinia/ECharts前端及Electron默认加载。
- 旧Electron renderer和PySide6入口保留。
- 多轮Python、TypeScript、Playwright和Electron启动验证。

### 范围外

- 重写策略、预测、回测、DecisionHub或真实下单。
- 强制依赖Redis服务。
- 删除旧界面和PySide6入口。

## 需求编号与验收编号

对应 `FR-001`、`FR-003`、`FR-004`、`FR-013` 至 `FR-015`、`FR-020` 至 `FR-022`、`AC-01` 至 `AC-12`。

## 进度

- [x] 2026-07-11 — 修复旧市场概览基线，255项Python测试通过。
- [x] 2026-07-11 — FastAPI兼容层、OpenAPI和缓存抽象完成。
- [x] 2026-07-11 — Vue前端、ECharts图表和Electron生产加载完成。
- [x] 2026-07-11 — Ruff、mypy、Vitest、Playwright和Electron启动冒烟完成。

## 意外情况与发现

- 原有4个GUI失败来自自定义指数卡片的纯文本断言，已改为验证可访问文本和富文本字段。
- Redis未运行不应阻止桌面启动，因此采用内存降级。
- Playwright Chromium第一次下载超时，随后环境中已有浏览器，端到端测试通过。

## 决策日志

- 2026-07-11 — FastAPI只做适配层，复用`ElectronBackendService`，避免策略出现第二份实现。
- 2026-07-11 — Vue成为默认Electron页面，旧renderer通过`CQP_FRONTEND=legacy`回退。
- 2026-07-11 — Redis只缓存短期API结果，Parquet仍负责历史K线持久化。

## 架构与接口

- FastAPI入口：`python -m china_quant_platform.api`。
- Electron生产页面：`frontend/dist/index.html`。
- 前端请求只访问本地FastAPI，不直连数据供应商。
- 缓存响应增加`cache.status`、`cache.cachedAt`；陈旧回退同步设置`dataHealth.status=STALE`和`block_signal=true`。

## 里程碑

### 里程碑1 — 基线和FastAPI

抽取HTTP适配边界，保留现有Python服务和接口字段，增加TestClient契约测试。

### 里程碑2 — 缓存

实现Redis/Memory后端、TTL、缓存键、单进程请求合并和上游失败陈旧回退。

### 里程碑3 — Vue/Electron

迁移搜索、策略、图表、回测、荐股、账户和主题；Electron默认加载Vue构建产物。

## 具体实施步骤

1. 修复旧GUI测试并记录基线。
2. 新增FastAPI app factory、请求模型和错误处理。
3. 接入缓存适配器，保留Parquet网关。
4. 创建Vue工作台、Pinia分析状态和ECharts图表。
5. 更新Electron启动、Vite开发和Windows批处理入口。
6. 更新决策文档、README、任务和追踪矩阵。

## 验证与验收

- Python：`pytest`、`ruff format --check`、`ruff check`、`mypy`。
- 前端：`npm run build`、`npm run test:unit -- --run`、`npm run test:e2e`。
- 服务：健康接口、OpenAPI路径、Redis不可用降级和陈旧数据阻断。
- Electron：生产Vue页面启动8秒内保持进程存活，后端子进程自动启动。

## 可复现性、幂等性与恢复

缓存键由接口、版本和规范化payload摘要生成；前端保存最近成功分析和账户输入；刷新失败不清空旧数据；旧界面和PySide6入口可回退。

## 风险与缓解措施

- 上游接口不稳定：缓存和数据健康门禁。
- 前端请求竞态：AbortController和请求代次。
- Vue构建产物过大：后续可用ECharts分包，当前不影响功能。
- Redis部署差异：默认内存降级。

## 产物与备注

主要产物为 `src/china_quant_platform/api`、`src/china_quant_platform/infrastructure/cache_backend.py`、`frontend/` 和更新后的Electron入口。

## 结果与复盘

当前迁移保持核心策略单一来源，255项Python测试、Ruff、mypy、Vitest、Playwright和Electron生产启动冒烟均已通过；后续可继续做ECharts分包和真实Redis实例压力测试。
