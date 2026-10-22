# 持久化资料库与审核记录

Type: task
Status: ready-for-agent
Blocked by: 01, 02, 06

## 目标

使用 SQLite 和本地文件系统保存业务状态、不可变工件和追加式审核决定。

## 范围

- ResearchProject、ResearchRun、Work、SourceVersion 和 Evidence
- Artifact、ReviewDecision 和 SkillVersion
- SQLite FTS 全文检索
- 工件版本与派生失效
- 删除来源、索引和受控全文

## 验收

- Agent 输出在 Schema 验证后事务性保存
- 同一成果不会因不同 URL 重复入库
- 修改审核产生新记录而非覆盖
- 删除来源后依赖工件不再显示为有效证据

## Comments
