# 接入首批资料来源

Type: task
Status: ready-for-agent
Blocked by: 01, 04

## 目标

通过 `SourceAcquisition` 模块接入 arXiv、GitHub、RSS/Atom 和手动 URL。

## 范围

- 查询、分页、限流、缓存和重试
- URL 规范化和来源元数据统一
- GitHub 仅处理约定范围的仓库资料
- RSS/Atom 仅处理白名单 Feed
- 手动 URL 遵守访问和保存策略

## 验收

- 四类来源输出统一 Candidate 和 SourceRef
- 单个来源失败不影响其他来源
- 限流与不可重试错误可区分
- 网络集成测试可用录制 fixture 离线运行

## Comments
