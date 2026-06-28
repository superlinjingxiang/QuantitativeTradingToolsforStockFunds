# 数据契约

规范性的机器可读Schema位于 `../../spec/contracts/`。

## 核心原则

- 所有外部来源记录必须保留供应商、接收时间、源时间戳、Schema版本和质量状态。
- 供应商特有字段在适配器边界完成标准化。
- 领域逻辑使用标准ID和有类型模型，不使用原始字典。
- 时间戳必须带时区；`trade_date` 和交易时段必须显式表示。
- 时点字段必须包含该值首次可被观察到的时间。

## 数据供应商协议

```python
class MarketDataProvider(Protocol):
    async def search_security(self, keyword: str) -> list[SecurityRef]: ...
    async def get_quote(self, security_id: str) -> Quote: ...
    async def get_bars(self, request: BarsRequest) -> list[Bar]: ...
    async def subscribe_quotes(self, security_ids: list[str]) -> AsyncIterator[Quote]: ...
    async def get_corporate_actions(self, request: CorporateActionRequest) -> list[CorporateAction]: ...
```

供应商能力必须可查询。若供应商不支持分钟历史、实时深度或某基金字段，应返回有类型的“不支持能力”结果，不得静默近似。

## 标准实体

- `SecurityRef`：稳定ID、代码、名称、资产类型、交易所、币种、上市日期和状态日期。
- `Quote`：买卖盘、最新价、成交量额、源时间/时点时间/接收时间和质量状态。
- `Bar`：周期、开高低收、成交量额、交易时段和复权元数据。
- `FundNav`：正式单位净值、累计净值、披露/时点日期；估算净值必须使用不同类型。
- `CorporateAction`：行为类型、公告/登记/除权日期以及现金和股份影响。
- `DataHealth`：新鲜度、完整性、一致性、授权和阻断等级。
- `AnalysisReport`：完整的用户可见策略结果和来源信息。

## AnalysisReport不变量

只有同时满足以下条件，报告才能包含可交易操作：

- `data_health.block_signal == false`；
- 已设置 `as_of` 和 `valid_until`；
- 包含策略、模型、规则和数据快照版本；
- 概率输出有效且已归一化；
- 存在最终风险决策；
- 解释同时包含正向因素和负向/风险因素；
- 不交易结果包含有类型的原因。

详见 `../../spec/contracts/analysis_report.schema.json`。

## 错误分类

`DataUnavailable`、`DataStale`、`DataInvalid`、`UnauthorizedData`、`RuleMissing`、`InsufficientHistory`、`ModelOutOfDistribution`、`ProviderRateLimit`、`Cancelled`、`InternalError`。

错误必须包含：面向用户的安全提示、工程详情/错误码、是否可重试，以及是否阻止信号生成。
