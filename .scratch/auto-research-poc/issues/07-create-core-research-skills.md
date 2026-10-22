# 创建核心研究 Skills

Type: task
Status: claimed
Owner: Kimi
Blocked by: 03, 04, 06

## 目标

实现计划、采集、筛选、解读、综合和证据校验六个内部 Skills。

## 范围

- `plan-research`
- `collect-sources`
- `triage-sources`
- `analyze-source`
- `synthesize-topic`
- `verify-evidence`
- 为每个 Skill 建立 Schema、样例、预期结果、CHANGELOG 和上游说明

## 验收

- Skills 不直接访问任意 Shell、网络、文件或数据库
- 所有输出同时具有 JSON、Markdown、证据、警告和版本
- 未找到证据的结论被标记为推断或拒绝
- 查询扩展需要人工确认后执行

## Comments
