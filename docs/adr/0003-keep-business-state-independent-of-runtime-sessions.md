---
status: accepted
---

# 业务状态独立于 Runtime Session

Pi Session 只用于执行上下文和运行轨迹，不作为研究任务、来源、证据、审核或工件的事实源。业务状态由 AutoResearch 自己的存储和工作流模块维护，使 Runtime、模型或 Session 格式可以替换而不破坏研究资料库。

## Consequences

Agent 不能直接写业务数据库；它提交结构化工件，由应用模块验证后事务性保存。Runtime 原始事件只作审计附件，并转换为稳定的领域事件供 CLI 和未来前端使用。
