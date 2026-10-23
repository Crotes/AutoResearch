# 开发指南

## 环境

- Python 3.12
- `uv`
- Windows PowerShell、macOS 或 Linux shell

在仓库根目录执行：

```powershell
uv sync --extra dev --locked
uv run autoresearch --version
```

### 持久化资料库

`SqliteResearchLibrary` 接受一个 SQLite 文件路径和可选的正文目录路径。SQLite 文件保存业务状态、证据关系、审核决定和 FTS5 索引；`AccessPolicy.PERSIST` 的正文写入内容寻址目录，`CONTROLLED`/`METADATA_ONLY` 不写入正文。资料目录和 SQLite 文件应放在 `.autoresearch/` 或其他未纳入 Git 的实验数据目录。

来源删除是可审计的 tombstone 操作：来源、历史工件和审核决定保留，正文/分块/来源索引移除，直接引用及其派生工件变为 `stale`。失效工件不会出现在默认检索中，也不能作为新工件的依赖。工件提交先以对应 Skill 的版本化 JSON Schema 校验，再把证据校验、版本分配和 FTS 更新放在一个 SQLite 事务中完成。

SQLite 连接允许由 MCP 线程池进入，但 `SqliteResearchLibrary` 会以进程内锁串行化同一连接上的事务和查询。该模型面向单进程、低并发 PoC；不要在多个进程间共享同一个 Adapter 实例。

若本机全局 Python 环境存在冲突，可直接使用项目虚拟环境中的可执行文件，例如 `.venv\Scripts\pytest.exe`。运行数据默认写入 `.autoresearch/`，该目录不进入 Git。来源连接器的 HTTP 响应缓存默认写入 `.autoresearch/cache/`（TTL 24 小时，命中即离线可用）。

## 验证

提交前执行完整检查：

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

离线纵向切片：

```powershell
uv run autoresearch demo --output .autoresearch/demo-export
```

完成标准是四项静态/自动检查均成功，相关验收场景得到验证，任务文件记录结果。

## 代码布局

| 路径 | 职责 |
| --- | --- |
| `src/autoresearch/domain/` | 不依赖基础设施的领域记录、事件和错误 |
| `src/autoresearch/application/` | 工作流与用例编排；`application/content/` 为内容处理（格式检测、正文提取、规范化分块、证据锚点、访问策略闸），`application/identity.py` 为成果身份解析与人工纠错 |
| `src/autoresearch/ports/` | Runtime、来源和工件等稳定接口 |
| `src/autoresearch/adapters/` | 内存、Pi、SQLite 和网络等接口实现 |
| `schemas/` | 跨进程和持久化边界的 JSON Schema |
| `tests/unit/` | 纯逻辑和单模块测试 |
| `tests/contracts/` | 稳定契约及固定样例验证 |
| `tests/integration/` | 多模块纵向流程验证 |
| `skills/` | 版本化研究判断规则 |
| `tools/` | Skill 可调用的受控确定性能力 |
| `workflows/` | 版本化顶层流程定义 |
| `.scratch/auto-research-poc/` | 产品规格、本地任务和临时原型 |

依赖方向为 `CLI → Application → Domain ← Adapters`。领域代码不导入 Adapter；Skill 不直接改变工作流状态或业务数据库。

## 增加功能

1. 从已认领任务提取可观察验收场景。
2. 先确定变更属于 Domain、Application、Port、Adapter、Tool 还是 Skill。
3. 在最窄边界增加测试，再实现行为。
4. 按协作文档的同步矩阵更新契约与说明。
5. 执行完整检查并将结果写入任务的 `## Answer`。

## 私有数据

测试使用人工构造或明确可公开的固定样例。真实研究数据保存在忽略目录或仓库外；需要共享时使用实验室批准的私有存储，不通过提交、Issue、PR 或 Session 日志传递。
