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
- 2026-10-23：实现分六个切片完成——A SQLite v3（完整 RunSpec、领域事件、运行与来源关联、按运行列工件）、B `WorkerRuntime.restore()` 跨进程恢复、C `application/export.py` 通用导出、D MCP 生产接线 `wiring.py`（默认连接真实 SQLite，`--demo` 保留 Fake）、E `ResearchWorkflow` 深模块 + `artifact_policy.py` 提交策略包装器、F CLI 命令组（project/run 命令、退出码 0/2/3/4/5、`--json`）。所有自动测试与静态检查通过。
- 2026-10-23：真实纵向验收（真实 deepseek-flash + arXiv + MCP）暴露三个任务 09 内缺陷并已修复——① `start`/`resume` 未阻塞到稳定点（补 `WorkerRuntime.wait_for_settlement()`）；② 未 `set_model` 导致 pi 默认用 anthropic 模型（补首次 prompt 前 `set_model`，模型/端点从 `PI_MODEL_*` 读取）；③ MCP 在 run 落库前启动导致 `get_run` 失败（`PiRuntimeAdapter` 增加 `persist_run` 回调，spawn 前落库）。

## Answer

### 自动验证

- `pytest -W error`：287 passed
- `ruff check .` / `ruff format --check .`：通过
- `mypy`（strict，53 源文件）：通过

### 真实纵向验收（`.autoresearch/`，未入库）

`run start` 用真实 deepseek-flash + arXiv/GitHub 阻塞到选源闸门（`review_required` / `overviews_ready`），生产 MCP 连接成功并真实物化 4 个来源、写入同一 SQLite（`run_source_versions` 关联），`request_human_review(source_selection)` 归一化为领域事件。跨进程恢复、审核门、取消、导出由自动测试覆盖（Fake 纵向切片走完整三层工件）。

### 发现但未在本任务修复（来源策略，超范围）

arXiv 源在论文 `license` 字段缺失时被 `license_access_policy` 映射为 `metadata_only`（ADR-0005 的保守策略），导致摘要正文不保存、`source_chunks` 为空，`submit_artifact` 的证据锚点校验因此拒绝所有速览。真实候选已返回且物化成功，失败原因由 Agent 明确写入审核请求（未静默隐藏），但「每个候选都有速览」无法达成。该缺口属于任务 05/07 的来源适配器与访问策略，需后续任务决策（调整 ADR-0005 或 arXiv 摘要的许可映射），不在任务 09 的 CLI 工作流范围内。

### 结论

CLI 工作流基础设施（状态机、恢复、审核门、取消、导出、生产 MCP、失败可见性）已交付并通过全部自动验证；真实问题纵向因上述来源策略缺口未能产生速览/解读/总结工件，如实记录为后续任务。
