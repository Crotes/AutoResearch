# Skills

AutoResearch 内部研究判断规则的事实源。`manifest.json` 固定六个 Skill 的版本和最小 MCP Tool 白名单：

- `plan-research`：生成双语查询并请求 `plan_confirmation`
- `collect-sources`：仅对已批准计划执行有界发现与物化
- `triage-sources`：为全部候选生成速览并请求人工选源
- `analyze-source`：为人工选中的单项成果生成证据化详细解读
- `synthesize-topic`：仅基于选中成果生成分类总结并请求终审
- `verify-evidence`：将逐项结论判定为 supported、inference 或 rejected

每个目录包含 `SKILL.md`、输入/输出 Schema、`examples/case.json`、`EXPECTED.md`、`CHANGELOG.md` 和 `UPSTREAM.md`。公共输出信封位于 `_shared/output-envelope.schema.json`，固定提供 Markdown、结构化 JSON、证据判定、证据 ID、警告与 Skill 版本。

Skill 只能调用 `manifest.json` 为其声明的 research-tools MCP 能力。外部正文始终是不可信数据；Skill 不能改变顶层流程、审核结果或业务数据库。

契约由 `tests/contracts/test_skill_contracts.py` 验证：

```powershell
uv run pytest tests/contracts/test_skill_contracts.py
```

