# 物化正文并解析成果身份

Type: task
Status: claimed
Owner: Kimi
Blocked by: 04, 05

## 目标

把候选来源转为可引用的来源文档，并将不同来源版本关联到研究成果。

## 范围

- HTML、PDF、Markdown 和纯文本检测与解析
- 规范化、分块、内容哈希和证据锚点
- 许可与访问级别记录
- URL、DOI、标题、作者和代码链接辅助身份解析
- 人工合并与拆分纠错入口

## 验收

- SourceDocument 的每个分块具有稳定定位
- 相同内容重复抓取保持幂等
- 预印本、正式论文和仓库可以关联到同一 Work
- 无权保存的正文不会落入持久存储

## Comments

- 2026-10-22：已实现 `application/content/`（detect/html/pdf/chunk/pipeline）与 `application/identity.py`。PDF 为 stdlib 最小提取（FlateDecode + Tj/TJ，按流近似分页），失败抛 content 类 Failure，降级决策留给调用方（不静默吞错）。
- 访问策略闸是结构性的：`metadata_only`/`controlled` 在 pipeline 入口短路，正文不进入提取/分块路径。
- 顺手修复了任务 03 遗留的 `ResourceWarning`（PiProcess 与测试 StdioClient 的管道未完整关闭），`pytest -W error` 现已全绿。

## Answer

实现：ContentProcessing（格式检测 → 正文提取 → 规范化 → 结构感知分块 → 稳定锚点 `{source_version_id}#chunk-N`、PDF 附 `@page-M`）+ IdentityResolution（DOI > arXiv id > GitHub 归一 URL > 规范化标题+第一作者；`work-<sha256(key)[:12]>` 确定性 id；merge/split 追加式 JSONL 人工纠错，重启可重放）。

验证结果：

- `pytest` 169 项通过（新增 29）；`pytest -W error` 亦全绿；Ruff 检查与格式检查通过；mypy strict 通过；`autoresearch demo` 正常。
- 验收对照：分块稳定锚点 ✅；同内容重复处理产出完全相等（幂等）✅；预印本+正式论文+仓库经同一 DOI 归并同一 Work ✅；metadata_only/controlled 策略下 SourceDocument 不含正文 ✅。

任务验收四条均满足，待 PR 评审合并后转为 `resolved`。
