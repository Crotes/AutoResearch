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

若本机全局 Python 环境存在冲突，可直接使用项目虚拟环境中的可执行文件，例如 `.venv\Scripts\pytest.exe`。运行数据默认写入 `.autoresearch/`，该目录不进入 Git。

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
| `src/autoresearch/application/` | 工作流与用例编排 |
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
