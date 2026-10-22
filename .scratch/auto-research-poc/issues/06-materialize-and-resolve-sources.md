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
