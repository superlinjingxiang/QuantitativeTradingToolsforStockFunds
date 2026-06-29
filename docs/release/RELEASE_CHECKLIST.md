# MVP发布清单

> Source of truth: TASK-025 打包、恢复、安全与发布审计。本文记录Windows打包入口、冒烟测试、恢复/迁移、安全和发布证据。

## Windows打包

首版发布使用 PyInstaller one-folder 包作为Windows桌面交付物。发布机器必须使用Python 3.12和 `uv.lock` 中的依赖。

```powershell
uv sync --all-extras --dev
uv run pyinstaller packaging/china_quant_platform.spec --noconfirm --clean
```

产物目录：`dist/china-quant-platform/`。

## 发布前冒烟测试

```powershell
uv lock
uv sync --all-extras --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m china_quant_platform --version
uv run python -m china_quant_platform.release.audit
uv run pyinstaller --version
```

## 数据迁移与恢复

- 首次启动由 `bootstrap_runtime(create_dirs=True)` 创建 `data/`、`logs/`、`reports/`。
- 模拟账户使用 `SimulationAccountState` JSON快照恢复，写入新快照前保留旧快照。
- 每次发布刷新并校验 `MANIFEST.sha256`。

## 凭据管理

- 真实数据供应商凭据不得进入源码、测试、文档、日志、报告、安装包或清单。
- 允许来源仅为环境变量、系统凭据存储或本地忽略的 `.env`。
- 发布审计命令会扫描嵌入式密钥模式，命中时发布失败。

## 可观测性

- 数据健康、任务取消、领域错误和模拟订单拒绝都必须保留结构化原因。
- 报告和信号必须包含数据快照、策略版本、模型版本、规则版本和checksum。
- 发布包必须携带 `MANIFEST.sha256`，便于离线校验文件一致性。
