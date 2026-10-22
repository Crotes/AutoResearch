---
status: accepted
---

# 将研究成果身份与来源版本分离

同一研究成果可能同时存在预印本、正式论文、代码仓库、作者博客和视频讲解。AutoResearch 使用 `Work` 表示成果身份，使用 `SourceVersion` 表示具体来源与版本，从而完成成果级去重，同时保留各来源的独特内容、许可和证据位置。

## Consequences

去重不能只比较 URL；系统需要身份解析、候选合并和人工纠错。审核以 `Work` 为主要对象，证据仍指向具体 `SourceVersion`。
