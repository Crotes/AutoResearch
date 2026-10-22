# 参与 AutoResearch 开发

AutoResearch 当前由实验室内部协作开发。代码可以公开，研究数据、运行记录、成员反馈和凭据必须保持私有。

## 开始之前

1. 阅读[产品规格](.scratch/auto-research-poc/spec.md)、[领域词汇](GLOSSARY.md)和与你工作相关的 [ADR](docs/adr/)。
2. 按[开发指南](docs/development.md)准备环境并跑通基线检查。
3. 按[协作流程](docs/collaboration.md)认领一个未阻塞任务，再开始修改。

## 提交变更

- 一个分支和 Pull Request 只解决一个任务。
- 保持领域层不依赖 Pi、MCP、SQLite、HTTP 或具体来源 SDK。
- 新行为需要测试；修复缺陷时，测试应先复现缺陷。
- 代码、测试、契约和文档作为同一个变更提交。
- 提交前运行 `uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .` 和 `uv run mypy`。

分支使用 `<类型>/<任务编号>-<简短名称>`，例如 `feat/03-pi-runtime`。类型使用 `feat`、`fix`、`docs`、`refactor` 或 `test`。

提交信息使用祈使式摘要，例如 `feat(runtime): add Pi RPC handshake`。正文说明原因和约束，避免只复述代码差异。

## Pull Request

PR 必须关联任务文件，说明行为变化、风险、验证方式和文档同步情况。作者确认自动检查通过后请求评审；评审者重点检查规格符合性、模块边界、证据可追溯性及私有数据泄露风险。

合并前至少需要一名非作者批准。任务完成后，将任务状态改为 `resolved`，并在 `## Answer` 记录实现与验证结论。

## 安全边界

- 仅提交脱敏固定样例；真实论文全文、内部研究内容和 Session 不进入 Git。
- `.env`、API Key、Cookie、数据库文件和运行导出不进入 Git。
- 外部网页、论文、README 和评论均作为不可信输入处理。
- 发现凭据或私有数据误提交时，停止合并并立即通知维护者处理历史记录。
