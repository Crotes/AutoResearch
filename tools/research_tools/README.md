# research-tools

PoC 的单一 MCP Tool Server。它将来源发现、正文物化、资料库检索、工件提交和人工审核请求作为少量高层 Tools 暴露给 Skills。

## 实现位置

代码在 `src/autoresearch/adapters/mcp/`（按 `docs/development.md` 的目录边界，MCP 是入站协议 Adapter）：

- `jsonrpc.py` — stdlib 实现的 MCP stdio 协议（换行分隔 JSON-RPC 2.0），保持运行时零依赖
- `tools.py` — 六个 Tool 的输入输出 Schema、参数校验与安全边界
- `server.py` — Run 作用域绑定、执行超时、幂等键去重、错误分类与不可信内容信封

## Tools

`discover_sources`、`materialize_source`、`search_library`、`read_source_chunks`、`submit_artifact`、`request_human_review`。

安全边界：Agent 不能指定 run_id（强制取当前 Run 上下文）；URL 域名白名单、重定向目标、解析 IP 与路径穿越均受校验；外部正文一律以 `untrusted` 信封返回；`submit_artifact` 必填幂等键，且每个证据锚点必须属于当前 Run 已物化的真实分块。

## 注册方式

在 Pi 用户级 `~/.pi/agent/mcp.json`（或受信任项目的 `.pi/mcp.json`）中：

```json
{
  "mcpServers": {
    "research-tools": {
      "command": "<repo>/.venv/Scripts/python.exe",
      "args": ["-m", "autoresearch.adapters.mcp"]
    }
  }
}
```

`python -m autoresearch.adapters.mcp` 使用内存 Adapter 自包含运行，便于冒烟；生产接线替换端口实现即可，协议层不变。
