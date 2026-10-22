---
status: accepted
---

# 使用 Pi RPC 作为 Worker Runtime

AutoResearch 选择 Pi `pi-coding-agent` RPC 作为唯一 Agent Runtime。Pi 提供语言无关的 JSONL 子进程协议和 Agent Skills 支持，表面积较小，适合由项目自己的控制面掌握任务、数据和权限；DeepSeek Harness 的 Python SDK 更便于快速接入，但其平台能力和预发布协议会扩大长期耦合面。

## Considered Options

- DeepSeek Harness Python SDK
- Pi coding-agent RPC
- 同时维护两个 Runtime Adapter

## Consequences

PoC 需要实现 Pi 子进程监督与 RPC Adapter；Python 研究能力通过 MCP Tools 暴露。必须固定 Pi 版本并做协议契约测试。若 Pi Adapter 维护成本不可接受，或 DeepSeek Harness 提供稳定兼容承诺并显著减少产品代码，应重新评估本决策。
