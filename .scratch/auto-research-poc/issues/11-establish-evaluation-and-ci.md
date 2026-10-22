# 建立轻量评测与 CI

Type: task
Status: ready-for-agent
Blocked by: 07, 09, 10

## 目标

用真实使用反馈比较 Skill 版本，并为公共仓库建立最小质量门禁。

## 范围

- 固定 3–5 个“Agent 自进化”研究问题
- 保存相关性、遗漏、证据和总结人工反馈
- 记录模型、Skill、耗时、Token、费用和错误
- Python 检查、测试、Schema、Workflow、Secret 扫描和镜像构建
- 小型离线评测

## 验收

- 同一问题可以比较两个 Skill 版本
- CI 不访问真实密钥或外部模型
- 评测失败不会被普通单元测试结果掩盖
- 能依据产品规格判断是否进入内部 Alpha

## Comments
