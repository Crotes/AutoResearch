# DeepSeek Harness 与 Pi：长期 Worker Runtime 产品化比较

> 调研日期：2026-10-22  
> 项目约束：Skill-first、先做 Python PoC、未来由 Java/Go 承担控制面、Docker 部署、公共仓库、实验室内部使用。  
> 资料范围：只采用 [DeepSeek Harness 官方仓库/文档](https://github.com/deepseek-ai/deepseek-harness) 与 [Pi 官方仓库/文档](https://github.com/earendil-works/pi)。本文中的 Pi 指当前 `earendil-works/pi`（包名 `@earendil-works/*`），不是其他同名项目。

## 决策结论

**长期默认 Worker runtime 推荐 Pi 的 `pi-coding-agent` RPC 模式；不推荐现阶段把实验性的 `pi-durable` 作为产品核心。DeepSeek Harness 保留为 Python 快速验证和能力对照实现。**

原因不是 Pi 在每项能力上都更多，而是它与本项目预期边界更一致：

1. Java/Go 控制面未来会拥有用户、权限、调度、队列、重试、配额和业务持久化，Worker runtime 应尽量小、可替换；Pi 明确定位为最小、可扩展 harness，并提供面向其他语言的长期 JSONL RPC 子进程接口。[Pi README](https://github.com/earendil-works/pi/blob/main/README.md)；[Pi RPC](https://pi.dev/docs/latest/rpc)
2. Pi 当前正式版本为 `v1.4.0`；DeepSeek Harness 当前最新为预发布 `v0.2.1-rc.2`，并明确声明 developer preview 阶段会发生兼容性破坏。[Pi Releases](https://github.com/earendil-works/pi/releases)；[DeepSeek Harness Releases](https://github.com/deepseek-ai/deepseek-harness/releases)；[DeepSeek Harness README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md)
3. 两者都支持按需加载 Skills 和 MCP；Pi 明确实现 Agent Skills 规范，适合把本项目的核心能力保存在可移植的 `.agents/skills` 中。[Pi Skills](https://pi.dev/docs/latest/skills)；[DeepSeek Harness Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
4. Pi RPC 原生提供 `abort`、明确的 `agent_settled` 完成边界和结构化工具事件；DeepSeek Harness 的专用 SDK wire 没有逐 Session cancel/close，必须改用其 ACP surface 才获得这些能力。[Pi RPC commands](https://pi.dev/docs/latest/rpc-commands)；[Pi JSON events](https://pi.dev/docs/latest/json)；[DSH SDK protocol](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)；[DSH ACP](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)
5. Docker 已是既定部署方式，因此 Pi 没有内置 sandbox 的缺点可在正确的容器边界内处理；DeepSeek Harness 自带的 sandbox 也只是共享内核和文件系统的 same-world confinement，官方同样要求容器、microVM 或远程执行器承担真正隔离。[Pi Security](https://pi.dev/docs/latest/security)；[DSH Sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox/README.md)

短期差异必须坦白：**Python PoC 使用 DeepSeek Harness 更省代码**，因为它有官方 Python SDK 和同版本 bundled runtime；Pi 没有 Python SDK，Python 需要按官方 RPC 文档示例管理 `pi --mode rpc` 子进程。但这个差异只存在 Worker 内部，不值得让长期控制面绑定到仍处预发布阶段的 DSH wire。[DSH Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)；[Pi RPC Python 示例](https://pi.dev/docs/latest/rpc#minimal-client)

## 一页比较

| 维度 | DeepSeek Harness | Pi | 对本项目的判断 |
| --- | --- | --- | --- |
| Python PoC | 官方同步 Python SDK，自动携带匹配的 runtime wheel并拉起子进程 | 无 Python SDK；按 JSONL RPC 启动子进程 | DSH 胜 |
| Java/Go 控制面 | 可实现 SDK wire 或标准 ACP；无第一方 Java/Go SDK | RPC 明确面向 language-independent integration；无第一方 Java/Go SDK | Pi 略胜 |
| Skills | 多 provider registry，支持 `.agents/skills`、项目/用户/custom/bundled 源和热更新 | 实现 Agent Skills 规范，支持 `.agents/skills`、Pi 目录、显式 skill 命令 | 二者都合格，Pi 的标准声明更利于移植 |
| Tools/扩展 | Cordis everything-is-a-plugin；工具、模型、Session、loop 都可替换；内建工具面很大 | TypeScript extensions 注册工具、事件、provider、命令和 UI；默认核心更小 | DSH 功能更全；Pi 边界更轻 |
| MCP | stdio 与 Streamable HTTP MCP client，工具进入原生 registry | 当前正式内置 stdio/Streamable HTTP MCP，支持 exposure 与资源工具 | 二者都合格 |
| Session 模型 | append-only `SessionEvent` 事件溯源日志，模型历史、回放、持久化由其派生 | JSONL entry tree，`id/parentId` 原地分支，活动分支构成模型上下文 | DSH 审计语义更强；Pi 分支操作更直观 |
| 事件与完成 | SDK 推送 raw session events/status；ACP 推送标准语义更新 | JSON/RPC 推送 message、tool、queue、retry、compaction；`agent_settled` 是最终自动工作边界 | Pi 对控制面更直接 |
| 取消 | SDK wire 无逐 prompt cancel/Session close；ACP 有 cancel/close | RPC `abort` 等待 idle，另有清队列、abort retry/bash | Pi 默认路径更完整 |
| 恢复 | SDK/ACP 可恢复持久 Session；恢复会修复中断的最终 turn；SDK 不恢复外部 shell/browser 进程 | coding-agent 可打开/切换 JSONL Session，但不承诺崩溃后续跑未完成工具；`pi-durable` 可恢复 pending work，但仍标 Experimental | 普通会话二者都可；真正 durable task 暂交控制面 |
| 并发 | SDK 可在一进程内拥有多 Session；ACP 明确支持一连接多 Session、每 Session 一个在途 prompt | RPC 操作当前 Session；运行中消息必须声明 steer/follow-up，产品并发宜用进程池 | DSH 单进程密度高；Pi 故障域更简单 |
| 隔离 | 有 read-only/workspace-write/full-access 策略，但不是完整安全边界 | 无内置 sandbox，进程权限即能力 | 两者都必须容器化；不要把 DSH sandbox 当租户隔离 |
| 持久化 | Session persistence seam、JSONL backend、flush 与 single-writer ownership | coding-agent JSONL Session；另有 experimental `pi-durable` 的 SQLite/JSONL storage | 业务事实均应在项目数据库，不应依赖任一 runtime 日志 |
| 协议成熟度 | SDK wire 无版本协商且官方不承诺预发布兼容；ACP 是标准协议但实现仍随 DSH 预发布版本演进 | RPC 是 Pi 专用协议，有完整文档和导出类型，但官方也称接口是 version-specific | Pi 相对稳定；两者都须锁版本和契约测试 |
| 版本成熟度 | `v0.2.1-rc.2`，developer preview，未安全审计 | `v1.4.0`，正式版本；项目仍快速演进 | Pi 胜 |
| 许可证 | MIT | MIT | 都适合公共仓库；分发修改版时保留许可证/版权声明 |
| 可替换性 | Profile/Cordis 内部可替换性强，但外部会接触较多 DSH Session/插件概念 | 核心更小，RPC 容易包在项目 adapter 后；Pi extension 本身仍是专有 API | Pi 更适合做可替换 Worker |

## 嵌入与后端集成

### DeepSeek Harness

官方 Python SDK 是本地子进程 SDK，不是远程 HTTP client。它懒启动同版本 `dsh --profile sdk`，通过 stdio 上的换行 JSON-RPC 2.0 通信，并在一个实例内复用 runtime。[Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)

官方同时提供 TypeScript SDK。SDK wire 包含 `initialize`、`session/prompt`、`session/resume`、`session/wait`、工作目录 get/set 和全局 `shutdown`，以及 session/subagent 通知；协议公开，因此 Java/Go 可以自行实现，但没有第一方 Java/Go client。[SDK family](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/README.md)；[SDK protocol](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)

如果 Java/Go 需要更完整控制，应优先驱动 `dsh --profile acp`：它通过标准 ACP v1 的 JSON-RPC stdio 提供 Session new/list/resume/close、prompt/cancel、权限请求、MCP 和模型选择。一条连接可运行多个独立 Session。[ACP server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)

`dsh web` 的 `/api` 是浏览器 BFF/Connection 内部面，不是适合后端长期依赖的通用 REST API。其契约由 TypeScript 构建生成，Session event stream 另有数据通道，并带浏览器 Host/Origin、启动 token 和 Cookie 语义。[API Gateway](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/api-gateway.md)；[公开部署](https://deepseek-harness.github.io/deepseek-harness/en/guide/public-deployments)

### Pi

Pi 有两条产品化入口：Node/Bun 可使用进程内 TypeScript SDK，其他语言或需要进程隔离时使用 `pi --mode rpc`。RPC 是双向 JSONL：stdin 接收命令，stdout 返回带 id 的响应并穿插 Session 事件，stderr 保留诊断。[Pi SDK](https://pi.dev/docs/latest/sdk)；[Pi RPC](https://pi.dev/docs/latest/rpc)

Pi 官方 RPC 文档直接给出 Python `subprocess.Popen` 最小客户端；Java/Go 需要实现的也是相同的换行 JSON framing、id 相关性和持续 stdout 消费。RPC `prompt` 成功仅表示接受/排队，调用方要等 `agent_settled` 才能确认 Pi 不会因 retry、compaction、steering 或 follow-up 自动继续。[Pi RPC lifecycle](https://pi.dev/docs/latest/rpc#run-lifecycle)

**判断：** Python 首次接入 DSH 更方便；一旦项目把 runtime 隔离在 Worker 容器，并通过自己的队列/API 与控制面通信，Pi 多写的只是一层很薄的 RPC adapter，而长期获得的是更简单的边界与更成熟的发行版本。

## Skills 与扩展机制

### Skill-first 适配度

Pi 会启动时只把 Skill 的名称、描述和路径加入提示，任务匹配后才读取完整 `SKILL.md`；支持 `~/.agents/skills` 与项目 `.agents/skills`，并明确实现 Agent Skills 规范。[Pi Skills](https://pi.dev/docs/latest/skills)

DeepSeek Harness 也使用目录 `SKILL.md`/flat Markdown 的按需加载模型，并支持项目 `.agents/skills`、用户 skills、custom 目录、bundled/provider 来源。它的 registry 能合并本地、嵌入式或远程 provider，并通过 `skill` tool 加载正文。[DSH Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)

因此，本项目应把可移植知识放在 `.agents/skills/<name>/SKILL.md`，并只使用两边共有的 frontmatter/相对资源语义。不要让核心 Skill 依赖某一边专属的工具名、profile 修改或 extension API；需要执行能力时调用项目自己的脚本、HTTP API 或 MCP 工具。

### Tools 与 extensions

DeepSeek Harness 的 model adapter、tool registry、Session、agent loop 本身都是 Cordis plugin；运行时由 profile、bundle 和 patch 组合。优点是替换粒度细、内建工具和控制面丰富；代价是理解和升级整棵插件树的成本更高。[DSH Architecture](https://deepseek-harness.github.io/deepseek-harness/en/reference/)；[DSH Tool Catalog](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-catalog.md)

Pi extension 是同进程 TypeScript 模块，可注册 tool、command、event handler、provider、MCP server 和 UI。其工具 exposure、annotations 和 `tool_call` gate 能实现按策略审批；但 extension 拥有 Pi 进程的全部 OS 权限。[Pi Extensions](https://pi.dev/docs/latest/extensions)

两者都原生支持 stdio 和 Streamable HTTP MCP。对本项目而言，**MCP 是比 Cordis plugin 或 Pi extension 更好的跨 runtime 工具边界**；runtime-specific extension 只应承担加载、事件映射和权限钩子。[DSH MCP](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)；[Pi MCP](https://pi.dev/docs/latest/mcp)

## Session、事件、取消与恢复

DeepSeek Harness 的 Session 是 append-only `SessionEvent` 日志，模型历史、transcript、telemetry 和持久化从日志派生。核心事件包括 user/assistant message、tool call/result、turn/step start/end 和 request header/context，适合审计与重放。[DSH Session](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)

其 SDK `session/prompt` 返回的 `messageId` 只代表 durable enqueue，不是 prompt result；高层 SDK 收集到 Agent 下一次整体 idle，因此同一 Session 并发入队可能让结果区间混入其他工作。SDK wire 没有 per-prompt cancel 或 per-session close；ACP 才具备一 prompt/Session 的清晰结算与 cancel/close。[DSH SDK server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/server/README.md)；[DSH ACP](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)

Pi coding-agent 的持久 Session 是 JSONL entry tree；每条记录通过 `id/parentId` 形成分支，活动分支提供下一次模型上下文，compaction 只改变后续投影而不删除旧 entry。[Pi How it works](https://pi.dev/docs/latest/how-pi-works)；[Pi Session format](https://pi.dev/docs/latest/session-format)

Pi RPC 的事件区分低层 `agent_end` 与最终 `agent_settled`，工具执行以 `toolCallId` 关联 start/update/end。`abort` 会中止当前操作并等到 Session idle；运行中新增消息必须明确选择 steer 或 follow-up，避免隐式竞态。[Pi JSON events](https://pi.dev/docs/latest/json)；[Pi RPC commands](https://pi.dev/docs/latest/rpc-commands)

普通 Pi coding-agent Session 可以继续、切换和分支，但官方没有承诺在进程崩溃后自动续跑未完成工具。另一个包 `@earendil-works/pi-durable` 提供任务先提交、崩溃后恢复、SQLite/JSONL backend 和幂等 request id，但官方明确标为 Experimental、API 可随发布变化。[Pi Durable](https://github.com/earendil-works/pi/blob/main/packages/durable/README.md)

**产品边界：** 现阶段无论选择哪一个 runtime，都让 Java/Go 控制面及 PostgreSQL 成为 Job 状态、幂等、重试和恢复的事实源。runtime Session 只作为模型上下文和审计附件；崩溃后由控制面决定恢复 Session、重开 Worker，还是从已落库 checkpoint 重跑。

## 并发、隔离与持久化

DSH SDK server 可让一个 runtime 拥有多个 Session；ACP 明确支持一连接多 Session，并在每个 Session 内限制一个在途 prompt。密度较高，但插件树、凭据和进程崩溃也是共享故障域。[DSH ACP concurrency](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)

Pi RPC 面向当前 Agent Session，可 new/switch Session，但并不把一条 RPC 连接定义为并发多 Session server。产品并发应由外部 worker pool 提供：一个容器/进程运行一个活动 Job，内部工具可以按 Pi 的执行策略并行。这更耗进程，但资源核算、取消和故障隔离更直接。[Pi RPC commands](https://pi.dev/docs/latest/rpc-commands)

DSH 持久化 seam 以 Session log 为中心，官方 JSONL backend 有 flush 与 single-writer ownership；Pi coding-agent 默认以 JSONL Session 文件持久化。两者都不是面向产品查询、多人授权或分析的业务数据库。[DSH Persistence](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)；[Pi Sessions](https://pi.dev/docs/latest/sessions)

安全方面没有“直接在宿主机跑即可”的赢家：

- DSH 有文件效果层面的 read-only/workspace-write/danger-full-access 和 fail-closed 检查，但官方说明它共享 host kernel/filesystem、未经过安全审计、不能作为唯一安全控制。[DSH Safety](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)；[DSH Sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox/README.md)
- Pi 明确没有内置 sandbox；project trust 只控制是否加载项目资源，不限制模型随后调用工具。官方要求不可信或无人值守任务使用容器、VM、microVM 或 policy-controlled sandbox。[Pi Security](https://pi.dev/docs/latest/security)；[Pi Containerization](https://pi.dev/docs/latest/containerization)

本项目应采用完整进程容器隔离，而不是只隔离 shell tool：每个 Worker slot 独立 workspace、home/config、临时目录和短期凭据；限制 CPU/内存/PID、挂载和网络目的地。公共仓库中的不可信 README、Issue、网页与论文内容都可能形成 prompt injection，因此资料采集 Agent 不应拥有 GitHub 写权限、宿主 Docker socket 或长期云凭据。

## 协议、版本、许可证与可替换性

DeepSeek Harness SDK wire 很小，但官方明确写明没有协议版本协商，当前预发布阶段没有兼容承诺；项目 README 也明确预计 compatibility-breaking changes。即使使用标准 ACP，也仍需锁定 DSH 实现版本并做契约测试。[DSH SDK protocol limitations](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)；[DSH README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md)

Pi RPC 是 Pi 专用协议，不是行业标准；官方把命令行与 RPC 文档描述为 version-specific，并提供导出的 TypeScript protocol types。Pi 已进入 `v1.x`，因此相对 DSH 当前 `0.x-rc` 风险较低，但不能把 `1.x` 等同于 wire 永久稳定；仍需锁版本、回放 fixtures 和升级前契约测试。[Pi RPC](https://pi.dev/docs/latest/rpc)；[Pi Releases](https://github.com/earendil-works/pi/releases)

两者均为 MIT License，适合公共仓库、内部部署、修改与分发，前提是保留相应版权和许可证声明。[DSH License](https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE)；[Pi License](https://github.com/earendil-works/pi/blob/main/LICENSE)

真正的可替换性不能依赖许可证或“都是 JSONL”，而要由本项目自己建立：

```text
Java/Go Control Plane
  ├─ PostgreSQL / Object Storage / Queue（业务事实源）
  └─ WorkerRuntime contract
       ├─ start(runSpec)
       ├─ stream(runId) -> normalized events
       ├─ cancel(runId)
       ├─ resume(runId, checkpoint)
       └─ close(runId)
            ├─ PiRpcAdapter（默认）
            └─ DshAdapter（实验/备用）

每个 adapter -> 独立 Docker worker -> runtime 子进程
```

建议项目级标准事件只保留：`run_started`、`message_delta`、`tool_started`、`tool_finished`、`artifact_created`、`checkpoint`、`run_succeeded`、`run_failed`、`run_cancelled`。原始 Pi/DSH 事件作为带 runtime/version 的审计 blob 保存，不进入前端和核心数据库 schema。

## 推荐实施顺序

1. 定义与 runtime 无关的 `RunSpec`、标准事件和 `WorkerRuntime` adapter 契约。
2. Python PoC 默认实现 `PiRpcAdapter`：参考官方 Python 示例启动固定版本 `pi --mode rpc`，启动前订阅 stdout，等待 `agent_settled`，并实现 `abort` 与进程回收。
3. 所有研究流程写成 `.agents/skills`；资料源访问尽量使用独立 Python connector，再通过 MCP 或窄 CLI/HTTP 工具暴露。
4. Docker 中一 Job/Worker slot，不在一个进程内混跑不同用户；控制面负责超时、重试、幂等和 checkpoint。
5. 实现一个最薄的 `DshAdapter` 对照实验，可直接使用官方 Python SDK；用同一组任务测完成率、事件完整性、取消延迟、恢复、内存、冷启动、模型成本和升级破坏。
6. 只有数据证明 DSH 的能力收益超过迁移/版本风险时才切换默认 runtime。

## 何时反转为 DeepSeek Harness

满足以下任一“硬需求”并经实测后，可以把长期默认反转为 DeepSeek Harness：

- 团队确定长期保持 Python Worker，官方 Python SDK 的 bundled runtime、profile/plugin 管理显著降低维护成本，而 Pi RPC wrapper 成为真实故障来源；
- 产品需要在一个 runtime 内高密度并发多 Session，并且 DSH ACP 的 Session 隔离、取消、权限与持久化表现明显优于进程池方案；
- DSH 的事件溯源 Session、内建 subagent/team、schedule、workspace、approval 或 Web/desktop 能力成为必需功能，而非未来 Java/Go 控制面会重复实现的便利功能；
- DSH 发布稳定版本并给出可执行的协议兼容政策，SDK/ACP 接口具备版本协商或长期兼容测试，同时安全状态不再只是“未审计 developer preview”；
- 在目标研究任务基准上，DSH 对 DeepSeek 模型、tool calling、长上下文或并行 Agent 的质量/成本优势达到足以承担平台锁定的程度。

反过来，如果 Pi RPC 在后续版本出现频繁破坏、缺少所需权限交互或恢复能力，而 `pi-durable` 仍长期处于 Experimental，也应重新评估 DSH 或自建更薄的 Worker loop。

## 最终建议

- **长期默认：Pi `pi-coding-agent` RPC，外部进程池并发。**
- **短期便利：DeepSeek Harness Python SDK 可作为快速原型或对照 adapter。**
- **暂不采用：`pi-durable` 作为核心业务 runtime；等其脱离 Experimental 再评估。**
- **共同红线：** 两者都不能承担租户认证、业务任务数据库或唯一安全边界；这些属于本项目的 Java/Go 控制面与 Docker 隔离层。
- **防锁定策略：** `.agents/skills` + MCP + 项目标准事件 + 外部事实存储，任何 runtime-specific plugin/extension 都保持薄层。
