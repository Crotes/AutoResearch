# 建立 PoC 工程骨架与契约

Type: task
Status: resolved
Blocked by:

## 目标

建立最小 Python 工程、CLI 入口和共享 Schema，使后续实现围绕稳定接口展开。

## 范围

- 初始化 Python 项目和依赖锁定
- 创建领域模型、错误分类和领域事件 Schema
- 定义 `WorkerRuntime`、`SourceAcquisition` 和工件提交接口
- 建立工作流、Skills、Tools、Runtime、评测和基础设施目录
- 配置格式、静态检查、单元测试和 Schema 校验

## 验收

- 空实现可以通过全部检查
- JSON Schema 能验证一份示例 Run、Source、Artifact 和 Event
- 接口测试不依赖 Pi、网络或真实模型

## Comments

## Answer

已完成 PoC 工程骨架与契约：

- 建立 Python 3.12 项目、CLI 入口、开发依赖与 `uv.lock`
- 建立领域模型、六类错误、九类领域事件和稳定端口
- 建立 Run、Source、Artifact、Event 四份 JSON Schema 及有效样例
- 建立 Workflow、Skills、Tools、Pi Runtime、Evals 和 Infra 目录说明
- 增加 11 个离线测试，不依赖 Pi、网络或真实模型
- 配置 Ruff、严格 MyPy、Pytest 和公共仓库数据忽略规则

验证结果：

- `pytest`：11 passed
- `ruff check`：通过
- `ruff format --check`：通过
- `mypy`：通过
- CLI 冒烟测试：输出版本 `0.1.0`
