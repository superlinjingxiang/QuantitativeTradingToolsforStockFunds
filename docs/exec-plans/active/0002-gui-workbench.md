# GUI行情工作台执行计划

## 目的和用户可见结果

建立PySide6桌面应用外壳、证券搜索切换和实时/历史图表工作区。完成后，用户可以启动桌面窗口，看到持续可见的数据健康状态，在搜索结果中选择证券，并在同一选择上下文中查看缓存历史、实时状态和基础图表工作区。

## 背景与仓库定位

TASK-001至TASK-007已完成，基础仓库、领域模型、供应商协议、证券主数据、数据网关、数据质量门禁和市场规则引擎均已存在。GUI必须作为最外层适配器，不得把供应商请求、规则推断或阻塞计算直接写进窗口类。

## 范围

### 范围内

TASK-008至TASK-010。

### 范围外

真实生产供应商接入、完整指标/策略/预测引擎、模拟交易、复杂回测、安装包和真实账户。

## 需求编号与验收编号

FR-001至FR-005、AC-01至AC-03、AC-06、NFR-02至NFR-04、NFR-06、T-07、T-10、T-11、T-16。

## 进度

- [x] 2026-06-29 05:25Z — PySide6应用外壳、状态模型、后台任务抽象、数据健康横幅和GUI测试；TASK-008已完成。
- [x] 2026-06-29 06:05Z — GUI防抖搜索、键盘候选选择、原子化证券切换和旧代结果丢弃；TASK-009已完成。
- [ ] 实时/历史图表工作区、周期切换、叠加层和增量更新；TASK-010。

## 意外情况与发现

- 2026-06-29 — GUI测试在无显示环境中运行，`tests/conftest.py` 默认设置 `QT_QPA_PLATFORM=offscreen`。

## 决策日志

- 2026-06-29 — TASK-008使用 `ApplicationViewModel` 持有不可变状态快照，窗口只渲染状态；可取消后台任务使用Qt定时器抽象演示非阻塞取消，真实线程/进程执行留给后续任务。
- 2026-06-29 — TASK-009将搜索和选择事务放在ViewModel；窗口只做300ms防抖、候选渲染和键盘/鼠标事件转发。旧后台结果必须携带 generation，和当前 `selection_generation` 不一致时丢弃。

## 架构与接口

`ui/state.py` 定义状态枚举与 `AppUiState`；`ui/viewmodel.py` 定义Qt信号、状态转移和可取消任务句柄；`ui/main_window.py` 定义主窗口布局和 `run_gui()`。后续搜索和图表必须通过ViewModel或应用服务更新状态，不得在Widget中直接访问供应商。

## 里程碑

### 里程碑1——应用外壳

实现TASK-008，窗口可启动，状态可测试，取消和类型化错误可见。

状态：已完成。

### 里程碑2——搜索与原子化切换

实现TASK-009，连接证券主数据、选择代次、旧任务取消和候选键盘操作。

状态：已完成。

### 里程碑3——行情图表工作区

实现TASK-010，展示历史/实时价格与成交量，支持周期和叠加层状态。

## 具体实施步骤

- TASK-008已创建 `MainWindow`、`ApplicationViewModel`、`CancellableQtTask`、`AppUiState`、`UiRunState` 和 `UiTaskStatus`。
- `python -m china_quant_platform --gui` 可启动PySide6桌面外壳；`--version` 行为保持不变。
- 主窗口包含搜索输入、数据健康横幅、行情时间、取消/设置按钮、三栏工作区和市场/策略/回测/模拟账户/风险/知识中心页签。
- TASK-009已把 `SecurityMasterService` 接入 `ApplicationViewModel`，新增 `SearchCandidateState`、防抖搜索结果列表、候选高亮、上下/回车确认、选择时记录最近访问、递增 `selection_generation`、取消旧任务和旧generation结果丢弃。

## 验证与验收

TASK-008验证证据（2026-06-29）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，89个测试通过。
- 覆盖PySide6导入、状态健康映射、健康横幅渲染、Qt事件循环非阻塞取消和类型化错误可见性。

TASK-009验证证据（2026-06-29）：

- `uv run ruff format --check .` 通过。
- `uv run ruff check .` 通过。
- `uv run mypy src tests` 通过。
- `uv run pytest` 通过，93个测试通过。
- 覆盖T-07/T-10：本地搜索候选、键盘上下移动、回车确认选择、选择代次递增、旧任务取消、旧generation结果不覆盖新证券状态和证券主数据搜索回归。

## 可复现性、幂等性与恢复

GUI测试必须使用确定性fixture和offscreen Qt，不依赖真实供应商、网络、显示器或用户凭据。后台任务取消必须幂等。

## 风险与缓解措施

- 主线程阻塞：耗时工作通过ViewModel任务抽象接入，不在Widget槽函数中执行。
- 状态漂移：后续证券切换必须使用 `selection_generation` 丢弃旧代结果。
- GUI过早绑定业务：窗口只消费状态，数据、规则和质量逻辑继续留在对应服务层。

## 产物与备注

- TASK-008产物：PySide6主窗口外壳、状态模型、后台任务抽象、CLI GUI入口和GUI测试。
- TASK-009产物：GUI搜索控件、防抖候选、键盘确认、原子化选择事务、旧任务取消和 generation-aware 结果丢弃测试。

## 结果与复盘

TASK-010完成后填写，并记录进入研究/回测核心前的GUI剩余缺口。
