# 集成 Pi RPC Runtime

Type: task
Status: claimed
Owner: Kimi
Blocked by: 01, 02

## 目标

实现 `PiRuntimeAdapter`，用独立子进程执行 Skills，同时不向上层泄漏 Pi 协议。

## 范围

- 启动和监督 `pi --mode rpc`
- 实现 JSONL framing、请求关联、事件消费和 stderr 采集
- 映射 start、events、cancel、resume、inspect 和 dispose
- 将 Pi 事件归一化为领域事件
- 固定 Pi 版本并增加协议 fixture 测试

## 验收

- 可执行一个最小 Skill 并取得结构化结果
- 超时、异常退出、无效 JSON 和取消均产生明确错误
- 上层测试不引用 Pi RPC 类型

## Comments
