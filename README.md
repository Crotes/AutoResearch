# AutoResearch

AutoResearch 是一个面向实验室内部使用的 Skill-first 研究资料收集与分析系统。当前阶段是 PoC 工程骨架，目标和边界见 [产品规格](.scratch/auto-research-poc/spec.md)。

参与开发前请阅读[贡献指南](CONTRIBUTING.md)。任务认领、并行开发与文档同步规则见[多人协作流程](docs/collaboration.md)。

## 开发

需要 Python 3.12 和 `uv`。

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
```

当前代码包含领域契约、端口和离线 Fake Adapter，不包含 Pi、网络来源或模型集成。

## 离线纵向切片

Fake Adapter 可以在不连接网络、Pi 或数据库的情况下跑通两个人工审核门，
并导出速览、详细解读、分类总结、来源正文和领域事件：

```powershell
.venv\Scripts\autoresearch.exe demo --output .autoresearch\demo-export
```

可点击的临时状态模型位于
`.scratch/auto-research-poc/prototypes/workflow-state-machine.html`，直接用浏览器打开即可。

