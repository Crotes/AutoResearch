---
status: accepted
---

# 分离公共代码与私有研究数据

项目代码、Skills、Workflows、脱敏示例和公开评测进入 Apache-2.0 的公共 GitHub 仓库；全文、实际研究任务、成员反馈、Session、运行日志和凭据保留在受控存储中。公开代码便于协作和复现，但不意味着实验室研究数据公开。

## Consequences

仓库必须配置忽略规则、Secret 扫描和脱敏测试夹具。第三方 Skills 需要记录许可证、上游提交、本地修改和权限需求。
