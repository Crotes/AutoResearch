# 预期结果

- 每个草稿结论都得到 `supported`、`inference` 或 `rejected` 判定。
- `supported` 必须有当前 Run 内可读取的精确分块锚点。
- 有限任务结果不能外推为所有任务保证；该结论被拒绝并从事实性正文移除。
- 顶层 `evidence_ids` 只包含受支持结论的锚点。
- JSON 输出通过输入与输出 Schema 校验。
