# 使用 Fake Adapter 跑通纵向切片

Type: task
Status: resolved
Blocked by: 01

## 目标

在不连接 Pi 和外部网络的条件下，跑通研究运行、人工检查点、不可变工件和导出。

## 范围

- 实现工作流状态机与检查点
- 实现 `FakeRuntimeAdapter` 和内存来源 Adapter
- 使用固定样例产生候选、速览、详细解读和分类总结
- 支持暂停、审核、恢复、取消和导出

## 验收

- 一次示例运行可从创建走到完成
- 未经人工选择不能生成详细解读
- 失败后可从最近检查点恢复
- 导出目录满足产品规格

## Comments

- 采用两个不可绕过的检查点：`overviews_ready` 等待人工选择，`analyses_ready` 等待最终批准。
- 原型技能要求将 HTML 原型保存在单独的 throwaway Git 分支；当前仓库尚未初始化 Git，故临时原型保存在 `.scratch/auto-research-poc/prototypes/workflow-state-machine.html`，待任务 12 建库时再决定是否保留分支快照。
- 2026-10-22：Git 仓库已初始化并推送至 `https://github.com/Crotes/AutoResearch`（main 分支含原型文件）。原型已随主分支进入历史，不再单独建 throwaway 分支；后续原型按原型技能要求使用独立分支。

## Answer

已实现纯工作流状态机、`FakeRuntimeAdapter`、内存来源 Adapter、固定三层工件、事件流、暂停/审核/恢复/取消与导出。

验证结果：

- 未经人工选择调用 `resume` 会被拒绝，且不会产生详细解读。
- 模拟分析步骤中断后，状态为 `failed`，检查点仍为 `overviews_ready`；再次恢复可继续完成。
- CLI 示例完整生成 3 份速览、2 份详细解读、1 份分类总结、来源正文、运行信息、清单和事件流。
- `pytest` 19 项通过，Ruff 检查与格式检查通过，mypy strict 通过。
