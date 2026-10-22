# 预期结果

- 原始研究问题和显式排除条件保持不变。
- 中英文扩展查询均说明理由，并以 `inference` 标记。
- 输出的审核门固定为 `plan_confirmation/pending`。
- 调用 `request_human_review` 后结束，不调用来源发现能力。
- JSON 输出通过 `input.schema.json` 与 `output.schema.json` 校验。
