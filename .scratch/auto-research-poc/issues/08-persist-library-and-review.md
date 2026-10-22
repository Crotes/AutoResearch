# 持久化资料库与审核记录

Type: task
Status: claimed
Owner: Codex
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

- 2026-10-22：从已合并的 01-07 基线开始实现。先统一证据锚点为 1-based（`#chunk-1`），再接入 SQLite + 内容寻址文件存储；这避免采集管线和 MCP 在首块证据上出现不一致。

## Answer

- 新增 `SqliteResearchLibrary`、`ContentStore` 和版本化 SQLite migration：项目、运行、SkillVersion、Work identity、SourceVersion、Evidence、Artifact、ReviewDecision、幂等键和失效关系均持久化。
- `PERSIST` 正文按 SHA-256 内容寻址写入本地目录，使用临时文件 + `fsync` + 原子替换；`CONTROLLED`/`METADATA_ONLY` 不写入正文。重复的来源种类、规范 URL 和内容哈希返回同一来源版本；Work identity key 具有唯一约束。
- 工件提交在一个 `BEGIN IMMEDIATE` 事务中完成证据存在性验证、版本分配、证据/派生关系、幂等键和 FTS5 索引写入；重复幂等请求重放，载荷不同则拒绝。
- 审核决定只追加并带 `sequence`/`supersedes_id`；删除来源采用 tombstone，移除正文、分块和来源索引，并递归把直接引用及派生工件标记为 `stale`，搜索默认排除失效工件。
- 新增 SQLite、FTS、重启恢复、受控正文和失效传播测试；验证命令：`pytest --basetemp=.pytest-tmp`（192 passed）、`ruff check src tests`、`mypy src`。
- PR：[#7](https://github.com/Crotes/AutoResearch/pull/7)。合并后再将状态更新为 `resolved`。
