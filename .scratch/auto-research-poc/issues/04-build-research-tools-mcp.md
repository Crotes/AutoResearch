# 建立 research-tools MCP Server

Type: task
Status: claimed
Owner: Kimi
Blocked by: 01, 03

## 目标

向 Skills 暴露少量高层 Tool，并限制 Agent 的网络、文件和业务状态访问。

## 范围

- 实现 `discover_sources`、`materialize_source`、`search_library`
- 实现 `read_source_chunks`、`submit_artifact`、`request_human_review`
- 增加输入输出 Schema、超时、幂等键和错误分类
- 将外部内容标记为不可信数据

## 验收

- 每个 Tool 可以脱离 Pi 单独测试
- 非法路径、未允许域名和直接数据库写入被拒绝
- Agent 只能看到当前 Run 所需能力

## Comments
