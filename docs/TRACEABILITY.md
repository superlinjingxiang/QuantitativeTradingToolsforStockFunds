# 需求追踪矩阵

本矩阵是从产品意图到实施任务和验证证据的标准桥梁。范围或行为变化时必须更新。

| 用户故事/需求 | 功能需求 | 验收 | 任务 | 测试 |
|---|---|---|---|---|
| US-01 搜索并选择证券 | FR-001、FR-002 | AC-01、AC-02 | TASK-004、TASK-009、TASK-029、TASK-034 | T-07、T-10；证券主数据搜索/最近访问/P95性能测试；GUI防抖搜索、键盘选择、旧任务取消、旧代结果丢弃、6位代码回车兜底、QQQ美股符号兜底和联网搜索断开不阻断选择测试 |
| US-02 查看实时/历史行情和周期 | FR-003、FR-004、FR-005 | AC-02、AC-03、AC-06 | TASK-005、TASK-008、TASK-010、TASK-029、TASK-030、TASK-032、TASK-034 | T-07、T-08、T-11、T-16；K线Parquet缓存、增量补缺、陈旧Quote、实时订阅取消/重连、图表点渲染、周期/范围/复权/叠加层、实时增量更新、东方财富短重试、Yahoo日K/quote备用源、Yahoo美股native security id直连、同花顺优先路由、搜索断开后继续拉取行情、Yahoo日K兜底OHLC/received_at契约清洗、图表悬停价格提示和实时quote昨收基准涨跌幅测试 |
| US-03 理解当前策略 | FR-006、FR-012、FR-018 | AC-04、AC-10 | TASK-011、TASK-012、TASK-017、TASK-018、TASK-020 | T-13；SMA/EMA/MACD/RSI/ATR/布林带/VWAP、收益/波动/回撤/相对强弱、因子元数据、缓存键确定性、策略预热、RawSignal门禁、解释一致性、ETF轮动研究状态、A股多因子趋势研究状态和GUI当前策略面板测试 |
| US-04 查看概率化预期走势 | FR-007 | AC-05、AC-10 | TASK-019、TASK-020 | T-12、T-13；校准概率预测、收益分位数、期望回撤、Brier/LogLoss/ECE、样本不足/分布外/漂移/低置信度不交易和GUI预期走势面板测试 |
| US-05 理解操作状态与原因 | FR-008、FR-009、FR-020 | AC-04、AC-06、AC-10 | TASK-015、TASK-020 | T-13、T-17；组合仓位、可卖数量、现金对账、集中度、流动性、回撤、相关性风险门禁、AnalysisReport合成和GUI操作风险面板测试 |
| US-06 运行并检查回测 | FR-013、FR-014 | AC-07、AC-08、AC-09 | TASK-013、TASK-014、TASK-016、TASK-017、TASK-018 | T-01至T-05、T-09、T-14、T-15、T-18；事件优先级、策略时序、订单晚于信号、规则拒绝、部分成交、取消、checksum复现、费用/滑点/价差/流动性/延迟、公司行为、组合对账、绩效/校准/成本报告、CSV/HTML导出、ETF成本换手敏感性和A股年份/市场/行业拆解测试 |
| US-07 正确分析ETF和场外基金 | FR-016 | AC-11 | TASK-017、TASK-023 | T-02、T-06、T-15；ETF轮动基准、场外基金正式净值确认、申赎费用、截止时间顺延、周/月风险比较和估算净值隔离测试 |
| US-08 学习金融概念 | FR-017 | AC-04、AC-05 | TASK-024 | K线/T+/ETF/净值/回撤/期望值/概率校准内容测试；禁用收益承诺词、国际理论与中国市场规则显式区分、上下文帮助搜索和GUI知识中心筛选渲染测试 |
| US-09 策略决策与赚钱验证 | FR-021、FR-006至FR-009、FR-013至FR-015、FR-020、C-006 | SDA-001至SDA-006 | TASK-026 | `tests/unit/test_decision_hub.py`覆盖DecisionReport、门禁降级、历史赚钱证据、模拟盘证据和无真实下单路径；`tests/gui/test_analysis_panel.py`覆盖GUI决策证据面板；`tests/gui/test_app_shell.py`覆盖联网行情自动生成决策报告 |
| US-09 策略盈利证据深化 | FR-022、FR-013至FR-015、FR-020、FR-021、C-006 | EPV-001至EPV-006 | TASK-027、TASK-034、TASK-035、TASK-036 | `tests/unit/test_profit_validation_strategy.py`覆盖ETF盈利验证算法、周期参数、每年交易次数约束、成交量/流动性确认、最终样本外阈值不泄漏、十标的聚合证据和下跌市场不通过；`tests/gui/test_app_shell.py`覆盖策略期限/交易次数控件、回测页盈利验证结果和无模拟盘证据不升级执行候选；`tests/gui/test_chart_workspace.py`覆盖回测曲线按钮、历史最大利润 B/S 标记、交易次数上限和正常显示恢复；`tests/unit/test_ai_hedge_fund_integration.py`覆盖ai-hedge-fund独立研究入口、repo解析、API key预检查和子进程隔离；后续仍需成本/容量压力、参数敏感性、过拟合诊断、模拟盘偏差和DecisionHub EPV门禁集成测试 |
| 市场概览与自选 | FR-010、FR-011 | AC-02 | TASK-021、TASK-028、TASK-033 | 市场广度/成交额/波动状态测试；自选分组、当前信号、陈旧状态可见、当前选择稳定、GUI指数/自选列表测试；最近访问渲染点击、自选添加删除按钮、成交量柱标注、指数默认占位、自动刷新、quote失败日K兜底和联网诊断说明测试 |
| 模拟账户 | FR-015 | AC-08、AC-09、AC-12 | TASK-022 | T-08、T-09、T-18；模拟成交入账、数据陈旧阻断、T+1可卖拒绝、部分成交偏差、状态导出恢复、无真实下单路径和组合对账测试 |
| 报告与审计 | FR-019、FR-020 | AC-09、AC-10 | TASK-016、TASK-025 | T-09、T-14；运行清单、报告checksum、交易流水、CSV/HTML导出、固定报告夹具回归、发布审计CLI、AC/NFR/完成定义覆盖、PyInstaller打包入口、恢复/迁移/可观测性清单和嵌入式凭据扫描测试 |
| 领域契约与错误分类 | FR-020、C-005 | AC-06、AC-10、AC-11 | TASK-002 | Schema往返测试、领域不变量测试、错误分类测试 |
| 数据供应商抽象 | FR-001、FR-003、FR-004 | AC-06、AC-09 | TASK-003、TASK-030 | 供应商协议测试、确定性假供应商测试、取消与限流测试；同花顺配置读取、同花顺quote/K线映射、多源失败切换和默认provider优先级测试 |
| 数据质量门禁 | FR-003、FR-004、FR-020、C-005 | AC-06、AC-10 | TASK-006 | T-08、T-16；重复K线、非法OHLC、缺失K线、陈旧Quote、缺失字段、未授权供应商、跨源对账和信号阻断测试 |
| 中国市场规则引擎 | FR-013、FR-016、C-002、C-004 | AC-07、AC-08、AC-11 | TASK-007、TASK-013、TASK-014、TASK-023 | T-02至T-06、T-15；有效期边界、缺规则失败、T+可卖数量、涨跌停流动性、停牌、费用、基金净值语义、回测订单规则拒绝和涨停无对手方流动性拒绝测试 |
| GUI应用外壳 | FR-001至FR-010、FR-021、FR-022 | AC-01至AC-06、AC-12 | TASK-008、TASK-009、TASK-010、TASK-029、TASK-032、TASK-034 | PySide6导入、状态健康映射、短数据健康横幅、联网错误弹窗、搜索候选、键盘确认、QQQ回车选择、图表控件、策略期限/交易次数控件、“回测曲线/正常显示”双态按钮、回测页、悬停十字线、红绿成交量/涨跌幅趋势柱、非阻塞取消和类型化错误状态测试 |

## 需求编号来源

- 产品需求与用户故事定义在 `product-specs/PRODUCT_SPEC.md`。
- 工程和非功能需求定义在 `technical/TECHNICAL_SPEC.md` 与 `quality/ACCEPTANCE_CRITERIA.md`。
- 机器可读镜像位于 `../spec/requirements.yaml`。
- 已完成策略决策中枢门槛使用 `SDA-*` 编号；下一阶段盈利验证深化门槛使用 `EPV-*` 编号，定义在 `quality/ACCEPTANCE_CRITERIA.md` 与 `../spec/requirements.yaml`。
