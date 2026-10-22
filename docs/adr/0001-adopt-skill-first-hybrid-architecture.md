---
status: accepted
---

# 采用 Skill-first 混合架构

研究策略、相关性判断和三层解读需要快速演化，而任务状态、数据正确性和权限必须保持确定性。因此，AutoResearch 将稳定行为放入固定模块，将来源与处理能力封装为 Tools，将研究判断放入版本化 Skills；顶层工作流由确定性状态机解释声明式定义，Skills 不能绕过审核或扩大权限。

## Considered Options

- 将完整研究流程硬编码在 Java/Go/Python 服务中：可靠但实验速度慢
- 将所有流程交给 Agent 自主执行：灵活但无法保证状态、安全和恢复
- Skill-first 混合架构：在受控 seam 内保留研究灵活性

## Consequences

Skills、Tools、Workflow 和代码都必须版本化并接受测试；系统需要维护结构化输出契约和 Tool 权限策略。
