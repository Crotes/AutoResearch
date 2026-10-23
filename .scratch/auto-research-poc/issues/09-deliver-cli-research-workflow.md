# 交付 CLI 研究工作流

Type: task
Status: claimed
Owner: Kimi
Blocked by: 02, 03, 05, 07, 08

## 目标

让研究者通过 CLI 完成项目创建、研究运行、审核、恢复、取消和导出。

## 范围

- project create
- run start、status、events、review、resume、cancel、export
- 探索模式工作流
- 三层结果的终端入口和 Markdown 导出
- 失败状态与警告展示

## 验收

- 真实研究问题可完成完整工作流
- 所有候选先生成速览，只有选中成果生成详细解读
- 分类总结只引用已选成果
- 失败来源和缺失正文不会被静默隐藏

## Comments

- 2026-10-23：认领。PR #8 已合并，任务 08 转为 resolved。采用“前台执行到稳定检查点”的运行模型：`start`/`resume` 阻塞到审核闸门或终态，状态全部落 SQLite，下一次 CLI 调用从 SQLite 重建上下文；Pi Session 仅作执行上下文。决策记录见 ADR-0008。
