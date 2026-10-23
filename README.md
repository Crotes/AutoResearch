# AutoResearch

AutoResearch 是一个面向实验室内部使用的 Skill-first 研究资料收集与分析系统：确定性模块保证状态与数据正确性，受控 Tools 提供外部能力，版本化 Skills 承担研究判断，顶层流程由确定性工作流状态机解释，人工审核门不可被绕过。目标和边界见[产品规格](.scratch/auto-research-poc/spec.md)。

## 当前状态（PoC）

- 领域模型、9 种领域事件与 4 份 JSON 契约（`schemas/`），配套契约测试
- 纯函数工作流状态机，含两道人工审核门（选源、终审）
- `PiRuntimeAdapter`：一运行一 `pi --mode rpc` 子进程，固定 pi **1.4.0**，事件归一化与审计落盘
- research-tools MCP Server：六个受控 Tool（stdlib 自实现 stdio JSON-RPC），含域名白名单、不可信内容信封、幂等提交和 Skill JSON Schema 校验等安全边界
- 四类来源连接器：arXiv、GitHub、RSS/Atom 白名单和手动 URL，含分页、限流、重试、缓存与访问策略
- 内容处理与成果身份解析：HTML/PDF/Markdown/纯文本、稳定证据锚点、成果级归并和人工纠错
- 六个版本化核心研究 Skills，包含输入/输出契约、样例、证据判定、最小 Tool 白名单和三个人工审核请求点
- `SqliteResearchLibrary`：SQLite 事务、FTS5 工件检索、内容寻址正文、幂等工件版本、追加式审核和来源删除后的派生失效
- 离线 Fake 纵向切片：不连网、不连模型即可跑通完整流程并导出工件

尚未实现：完整 CLI（任务 09）和容器加固（任务 10）。任务全景见 `.scratch/auto-research-poc/issues/`。

## 快速开始

需要 Python 3.12 和 `uv`。

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
```

### 离线演示

```powershell
uv run autoresearch demo --output .autoresearch/demo-export
```

导出包含 run.json、events.jsonl、manifest.json、来源正文与三层工件（速览/详细解读/分类总结）。可点击的工作流状态机原型位于 `.scratch/auto-research-poc/prototypes/workflow-state-machine.html`。

### 真实 Pi 运行（可选）

1. 安装固定版本：`npm i -g @earendil-works/pi-coding-agent@1.4.0`
2. 复制 `.env.example` 为 `.env`，填入模型端点与密钥（`PI_MODEL_ID` / `PI_MODEL_BASE_URL` / `PI_API_KEY`）
3. 在 `~/.pi/agent/mcp.json` 注册 research-tools（示例见 [tools/research_tools/README.md](tools/research_tools/README.md)）
4. 冒烟脚本见 `.autoresearch/acceptance/`（本地生成，不入库）

## 架构

```text
CLI → Application → Domain
                   ↑
Adapters ──────────┘   （fake / pi / mcp / library）
```

- 依赖方向：`CLI → Application → Domain ← Adapters`；领域不依赖 Pi、MCP、SQLite、HTTP
- 业务状态独立于 Runtime Session（ADR-0003）；研究成果身份与来源版本分离（ADR-0004）
- SQLite 资料库和内容寻址正文的事务/删除策略见 ADR-0007；其余架构决策见 [docs/adr/](docs/adr/)，拓扑与深模块说明见 [docs/architecture/overview.md](docs/architecture/overview.md)
- 术语以 [GLOSSARY.md](GLOSSARY.md) 为准（含禁用同义词）

## 安全边界

公共代码与私有研究数据严格分离（ADR-0006）：全文、研究任务、Session、日志、凭据不进入仓库（`.gitignore` + GitHub Secret scanning / Push protection 双重防线）。外部网页、论文、README 均视为不可信数据。

## 参与开发

- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献指南
- [docs/collaboration.md](docs/collaboration.md) — 任务认领、分支/PR、文档同步矩阵
- [docs/development.md](docs/development.md) — 环境、验证命令、目录边界

## 许可证

Apache-2.0
