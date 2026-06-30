# 架构设计

## 系统形态

应用采用模块化Python桌面架构。领域逻辑和研究逻辑必须支持无界面运行；PySide6只作为最外层适配器。

```text
PySide6 视图 / ViewModel
        ↓ 命令和只读状态
应用服务 / 任务编排
        ↓
领域模型 ─ 策略 ─ 预测 ─ 风险 ─ 组合 ─ 回测 ─ 决策中枢
        ↓
规则引擎 ─ 数据质量 ─ 数据供应商抽象
        ↓
供应商API / WebSocket / Parquet / DuckDB / SQLite / 文件
```

## 依赖方向

外层可以依赖内层抽象，内层不得导入GUI或具体供应商模块。

```text
ui -> application -> domain
application -> data protocols / strategy / backtest / risk
decision -> domain / analysis / reporting / simulation
provider adapters -> data protocols + vendor SDKs
storage adapters -> repository protocols + storage libraries
strategy -> domain + indicators + factors
backtest -> domain + rules + execution models + portfolio
```

禁止的依赖：

- `domain` 导入 `ui`、供应商SDK、DuckDB、SQLite或HTTP客户端。
- `strategies` 直接调用供应商接口或解析交易所规则。
- `ui` 构造供应商请求或执行阻塞计算。
- `backtest` 使用GUI状态作为输入。

## 目标仓库结构

```text
china_quant_platform/
├── AGENTS.md
├── README.md
├── PLANS.md
├── TASKS.md
├── pyproject.toml
├── src/china_quant_platform/
│   ├── app/
│   ├── ui/
│   ├── domain/
│   ├── data/
│   ├── rules/
│   ├── indicators/
│   ├── factors/
│   ├── strategies/
│   ├── forecasting/
│   ├── backtest/
│   ├── decision/
│   ├── risk/
│   ├── portfolio/
│   ├── simulation/
│   ├── reporting/
│   └── infrastructure/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── regression/
│   ├── gui/
│   └── fixtures/
├── docs/
├── spec/
├── data/          # 忽略的运行时数据
├── reports/       # 忽略/生成的报告
└── logs/          # 忽略/生成的日志
```

## 核心服务

| 组件 | 职责 |
|---|---|
| `SecurityMasterService` | 可搜索、支持时点状态的证券身份与分类 |
| `MarketDataGateway` | 与供应商无关的历史/实时行情访问 |
| `DataQualityService` | 数据校验、新鲜度、对账与阻断状态 |
| `RuleEngine` | 按日期生效的可交易性和执行约束 |
| `IndicatorEngine` | 确定性时间序列指标 |
| `FactorEngine` | 版本化横截面/时间序列因子 |
| `StrategyEngine` | 生成原始信号及解释 |
| `ForecastEngine` | 经过校准的概率和收益/风险分布 |
| `RiskEngine` | 信号门禁、仓位计算和敞口约束 |
| `PortfolioEngine` | 现金、持仓、可卖数量、估值和盈亏 |
| `BacktestEngine` | 事件排序和模拟市场回放 |
| `SimulationBroker` | 使用实时数据进行模拟下单与成交 |
| `DecisionHub` | 汇总分析、回测、模拟盘和门禁证据，输出最终建议与执行候选状态 |
| `AuditService` | 保存数据、规则、信号和回测的版本化证据 |
| `TaskScheduler` | 可取消的后台任务和定时工作流 |

## 状态与并发

- Qt主线程只负责视图。
- 搜索、历史数据加载、订阅、策略计算和回测在可取消的工作线程/任务中运行。
- 证券切换使用单调递增的 `selection_generation` 标记；旧代结果必须丢弃。
- 所有后台操作返回有类型的成功、降级或错误状态；异常不得直接修改UI。

## 架构变更规则

修改依赖方向、核心服务归属、存储边界或执行顺序时，必须在 `docs/DECISIONS.md` 记录决策，并创建执行计划。
