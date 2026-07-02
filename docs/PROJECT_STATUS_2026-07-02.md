# 项目进度快照 - 2026-07-02

## 当前定位

本项目已经从原始规格包推进为可运行的 Python 量化研究桌面工具。当前核心目标不是直接真实下单，而是围绕“策略到底能不能赚钱、回测是否可信、模拟盘是否能验证”建立可解释的研究闭环。

真实交易/API 下单仍保持禁用。任何 BUY/SELL 类建议都只能作为研究或模拟盘候选，不能被解释为保证盈利或真实交易指令。

## 已具备功能

- Python 3.12 + uv 可复现工程、PySide6 桌面入口、PyInstaller 打包入口、Electron 桌面入口。
- Electron 壳层：通过 `start_electron.bat` 启动，自动拉起本地 Python HTTP 后端；Electron 只负责 UI、图表和交互。
- 多数据源行情链路：同花顺 iFinD/QuantAPI 可选优先，东方财富公开接口和 Yahoo chart/quote 兜底。
- 代码/名称搜索、6位 A 股/ETF 代码兜底、美股和港股符号兜底。
- K 线图表工作区：日线/分钟/周月线、复权、范围切换、价格轴、最新涨跌、成交量、涨跌幅柱、悬停十字线。
- 左侧自选、最近访问、指数模块；指数支持自动刷新、日K兜底和红绿高亮。
- 盈利验证策略链路：短线策略/长线策略、最大交易次数约束、量能/流动性确认、样本外回测、滚动前推、Brier 和可靠性等级。
- 相似历史区间概率预测：上涨/横盘/下跌概率、p05/p50/p95 收益区间、预期回撤、滚动校准覆盖率和下破率。
- DecisionHub 决策门禁：区分策略建议和执行状态，缺少模拟盘/门禁证据时保持 RESEARCH_ONLY 或 WATCH。
- 底部回测页：展示净收益、年化、最大回撤、相对基准、胜率、交易次数、阈值、Brier、交易流水和说明。
- 当前图表回测层：`回测曲线`/`回测信号` 均使用当前可见图表窗口，保持同一周期、复权、日期范围和横轴刻度，只叠加买卖点。
- ai-hedge-fund 独立研究入口：通过子进程调用外部仓库，不覆盖本项目主策略。
- Electron 前端初版：深色金融仪表盘布局，保留搜索、短线/长线策略、交易次数、周期/范围/复权、成交量、MA、回测信号、预测区间、指数/自选/最近访问、右侧四块决策卡和底部回测证据。

## 近期关键修复

- 修复输入框回车后不能立即按当前文本搜索/选择的问题。
- 修复东方财富搜索/K线/quote 断开时图表无数据的问题，增加本地代码兜底和 Yahoo 备用源。
- 修复顶部长错误条挤压输入框的问题，改为短状态 + 弹窗详情。
- 修复指数面板启动空白，增加主要指数自动刷新和红绿高亮。
- 修复图表价格、成交量和涨跌幅不可读问题。
- 修复右侧策略面板文案混淆：现在明确显示“策略建议”和“执行状态”。
- 修复 `回测曲线` 与当前图表不对齐的问题。
- 修复 `回测信号` 第一次点击显示后台策略信号的问题；现在第一次点击即生成当前图表窗口内的回测买卖点。
- 新增 Electron 本地后端 API，复用 Python 行情、盈利验证、概率预测、DecisionHub 和图表利润最大化回测。
- 修复 Electron 在 Windows 捕获/远程环境下黑屏的问题：显式关闭 GPU 加速并在 `ready-to-show` 后显示窗口。

## 当前验证结果

- `pytest tests/gui/test_chart_workspace.py tests/gui/test_app_shell.py tests/gui/test_analysis_panel.py`：33 passed。
- `pytest tests/gui/test_chart_workspace.py tests/gui/test_app_shell.py tests/gui/test_analysis_panel.py tests/unit/test_interval_forecast.py tests/unit/test_forecasting_engine.py`：41 passed。
- `ruff check src/china_quant_platform/ui/viewmodel.py src/china_quant_platform/ui/main_window.py src/china_quant_platform/ui/chart.py tests/gui/test_chart_workspace.py`：通过。
- `ruff check src/china_quant_platform/electron_api.py`：通过。
- `mypy src/china_quant_platform/electron_api.py`：通过。
- Electron 手工验证：`start_electron.bat` 可启动窗口；输入 `513300` 回车后成功显示图表、指数、右侧策略/预期走势/操作风险/决策证据，后端返回 `HEALTHY`、图表点和回测信号。
- 扩展预测验证池真实数据实验曾验证 22/22 标的成功，平均区间覆盖约 86%，下破率约 7%，方向 Brier 约 0.224，整体可靠性 MEDIUM。

## 剩余风险

- 当前策略仍是研究级策略，不能证明未来可赚钱。
- 模拟盘成交偏差、漏单/重复信号、容量压力、涨跌停/停牌压力和过拟合模型卡仍需继续加强。
- 同花顺 iFinD/QuantAPI 需要用户自行配置授权 token；无 token 时依赖公开接口和 Yahoo 兜底，稳定性受外部服务影响。
- Electron 初版仍是原生 HTML/CSS/Canvas，尚未引入前端工程化、自动化打包和完整 E2E 测试。
- Electron 的图表交互已覆盖主要查看/回测场景，但仍需要继续补悬停提示、键盘快捷键、模拟盘和知识中心深层交互。

## 下一阶段

1. 为 Electron 补端到端测试和打包脚本。
2. 将 PySide 中更细的自选列表、模拟盘、风险页、知识中心页逐项迁移到 Electron 的底部 Tab 内容。
3. 继续加强策略可信度：模拟盘验证、成交偏差、过拟合控制和多资产滚动验证。
4. 保持 Python 作为唯一策略/数据/回测后端，Electron 不直接实现赚钱算法。
