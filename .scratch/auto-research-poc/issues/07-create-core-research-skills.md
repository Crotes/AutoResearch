# 创建核心研究 Skills

Type: task
Status: resolved
Owner: Codex
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

- 2026-10-22：用户要求继续完成任务，Owner 由 Kimi 交接为 Codex；沿用 `feat/07-core-research-skills` 分支，不包含尚未合并的 PR #5。
- 六个 Skill 采用统一输出信封与最小 Tool 白名单；`plan-research` 使用独立 `plan_confirmation` 人工闸门，确认前停止来源发现。
- 2026-10-22：实现已提交并创建 PR #6，等待非作者评审与合并。
- 2026-10-22：PR #5 合并后同步 `origin/main`；README 与 research-tools 说明冲突已保留双方意图，合并后的 187 项测试及全部静态检查通过。

## Answer

实现已完成并提交至 PR #6，等待评审和合并后转为 `resolved`：

- 建立 `plan-research`、`collect-sources`、`triage-sources`、`analyze-source`、`synthesize-topic` 和 `verify-evidence` 六个 1.0.0 Skill 包。
- 每个包包含 ASCII `SKILL.md`、输入/输出 Schema、可验证样例、预期结果、变更记录和上游说明；原创 Skill 明确记录 Apache-2.0 与无第三方上游。
- `manifest.json` 固定每个 Skill 的最小 research-tools 白名单；公共输出信封统一 Markdown、结构化 JSON、逐结论证据判定、证据 ID、警告和 Skill 版本。
- `plan_confirmation` 加入 MCP 审核门；采集输入 Schema 只接受已批准计划，查询确认前不能执行发现。
- 证据契约要求 `supported` 结论至少携带一个精确分块锚点；证据不足时由 Skill 标记为 `inference` 或 `rejected`。

验证：全量 pytest 177 项通过；Ruff 检查和格式检查通过；mypy strict 通过；六个 Skill 均通过 `quick_validate.py`；`git diff --check` 通过。
