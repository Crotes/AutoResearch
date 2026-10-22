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

- 2026-10-22：已实现 `src/autoresearch/adapters/mcp/`（jsonrpc/tools/server/__main__）+ `ports/library.py` + `adapters/library.py`。为保持运行时零依赖，MCP stdio 协议用 stdlib 自实现，未引入官方 SDK。
- 安全边界落点：`submit_artifact` 的输入 Schema 不含 run_id（Agent 无法写其他 Run）；URL 域名白名单与路径穿越拒绝；外部正文统一不可信信封；幂等键去重；`tools/list` 仅暴露当前 Run 白名单。
- 冒烟发现：pi 的 codemode 控制台对中文 Tool 描述显示乱码（Windows 代码页），不影响模型经 API 收到的描述与调用；Pi 侧工具名为 `mcp__research_tools__<tool>`（连字符转下划线）。

## Answer

实现：六个 Tool（`discover_sources`、`materialize_source`、`search_library`、`read_source_chunks`、`submit_artifact`、`request_human_review`），经 `ToolContext` 绑定 Run 作用域，ThreadPoolExecutor 强制 30s 超时，错误统一映射为 `Failure` 六类并经 `isError` 返回。

验证结果：

- `pytest` 95 项通过（新增 41：六 Tool 脱离 Pi 的单测含全部拒绝路径、JSON-RPC 分帧、真实子进程 stdio 全周期、Tool Schema 的 jsonschema 校验）；Ruff 检查与格式检查通过；mypy strict 通过；`autoresearch demo` 正常。
- 真实 pi 冒烟通过（`.autoresearch/acceptance/mcp_smoke.py`）：pi 1.4.0 + deepseek-flash 经 `~/.pi/agent/mcp.json` 挂载 server，模型自主发现并调用 `mcp__research_tools__search_library`，返回结构化结果 `isError: false`。

任务验收三条均满足，待 PR 评审合并后转为 `resolved`。
