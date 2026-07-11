# 行情缓存与 Electron 迁移设计

## 背景

当前桌面端每次选择标的都会触发联网搜索、K 线和 quote 请求。公开接口会间歇超时或断开，且长期日线回测需要更多历史数据，导致用户感觉“每次都在重新联网、很慢”。同时 PySide6 足够承载 MVP，但图表和交互体验不如 Web/Electron 生态。

本设计的核心约束是：缓存和 Electron 都只能服务于“策略到底能不能赚钱、回测是否可信、模拟盘是否能验证”，不能绕开 Python 策略、回测、DecisionHub 和模拟盘证据模型。

## 分阶段方案

### 阶段 A：本地行情缓存

- 使用本地数据库记录标的、数据源、时间范围、周期、复权、字段版本、获取时间和数据健康。
- 日线、分钟线等大表优先落到 `data/cache/`，可选 DuckDB 或 SQLite 元数据 + Parquet 明细。
- `MarketDataProvider` 前增加 `CachedMarketDataProvider`：
  - 先读缓存，命中且未过期时直接返回。
  - 未命中或过期时后台刷新远端数据。
  - 刷新失败时，如果缓存可用，标记 `STALE` 但允许图表和回测继续运行。
  - 缓存返回必须保留原始 provider、schema_version 和 received_at，策略证据可追溯。
- 默认 TTL：
  - 日线：交易日收盘后刷新一次，盘中可使用最近缓存并后台更新。
  - 分钟线：盘中短 TTL，收盘后可长 TTL。
  - quote：短 TTL，只用于当前行情展示，不作为长期回测主数据。

### 阶段 B：Python 本地服务边界

- 保留 Python 作为唯一策略后端。
- 暴露本地 HTTP/WebSocket API，例如：
  - `GET /api/search?q=QQQ`
  - `GET /api/bars?security_id=SSE:513300&interval=1d&range=1y`
  - `POST /api/decision`
  - `POST /api/backtest`
  - `GET /api/cache/status`
- API 返回的决策结构仍来自 `DecisionReport`、`BacktestPanelState` 和 `ProfitBacktestResult`。
- 真实下单 API 必须继续受 `DecisionHub`、模拟盘证据和凭据治理门禁约束。

### 阶段 C：Electron 前端

- Electron 只负责 UI、图表、交互和打包壳。
- Python 服务随 Electron 启动为本地子进程，端口随机或使用命名管道，退出时一并关闭。
- Web 前端可使用更成熟的图表库，但必须展示同样字段：
  - 行情价格、涨跌、成交量、数据健康、provider 来源。
  - 策略期限、交易次数、盈利验证状态。
  - 净收益、年化、回撤、超额、胜率、交易次数、Brier、可靠性等级。
  - DecisionHub 门槛、模拟盘缺口和禁止真实下单边界。

## 是否立即迁移

当前不建议立即整体迁移到 Electron。优先级应为：

1. 本地缓存，减少重复联网和接口不稳定。
2. 策略回测页和决策面板直接接入盈利验证结果。
3. 模拟盘验证与偏差报告。
4. Electron UI 重构。

这样可以先解决“慢”和“无数据”的使用阻塞，同时不牺牲策略可信度。如果 Electron 提前做，也应只做壳层和图表，不重写策略算法。

## 2026-07-11重构落地

当前已采用“FastAPI + Vue + Electron”的桌面形态：FastAPI兼容原有四个API路径，Vue通过Pinia保存最近一次成功结果并后台重验证，Electron默认加载`frontend/dist`。Redis作为短期API热缓存优先使用，未启动时自动降级到内存；Parquet仍是历史K线持久缓存。

默认TTL为：健康5秒、报价10秒、搜索10分钟、分析15秒、荐股60秒。上游失败且存在缓存时返回`cache.status=STALE`并将`dataHealth.block_signal`置为`true`，前端保留上一次结果但不生成新的正式交易信号。

## 验收要点

- 断网或公开源失败时，历史缓存仍可支持图表和回测，并明确标记 `STALE`。
- 同一标的重复打开不应每次全量联网拉历史。
- 缓存数据进入策略前必须有时间戳、来源、复权和质量状态。
- Electron 前端不得直接实现赚钱算法，必须调用 Python 后端。
- 缺少模拟盘证据时，即使历史回测为正，最终执行候选仍不得升级为真实 API 下单。
