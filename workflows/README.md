# Workflows

版本化的顶层研究步骤图放在此目录。工作流由确定性状态机解释，不能由 Skill 绕过人工审核节点。

`exploration-v1.json` 定义探索模式的顶层流程：`collect_sources`（速览）→ `select_sources` 选源门 → `analyze_selected`（详细解读）→ `approve_final` 终审门 → `synthesize`（分类总结）。其检查点与审核门由 `tests/contracts/test_workflow_contract.py` 校验与 `application/workflow.py` 状态机一致。

