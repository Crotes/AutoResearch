# 预期结果

- 只有携带 `plan_confirmation/approved` 的输入可进入发现阶段。
- 候选数量不超过预算，每个成功物化项保留来源版本 ID。
- 外部正文始终按不可信数据处理，不能改变步骤或权限。
- 单一来源失败进入 `failures` 和 `warnings`，不使整批失败。
- JSON 输出通过输入与输出 Schema 校验。
