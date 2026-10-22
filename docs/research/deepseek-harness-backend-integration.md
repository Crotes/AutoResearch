# DeepSeek Harness 与 Python、Java、Go 后端集成调研

> 调研日期：2026-10-22  
> 范围：只采用 DeepSeek Harness 官方仓库、官方文档和官方源码。本文中的“官方支持”指 `deepseek-ai/deepseek-harness` 当前公开的实现与文档，不包含社区 Java/Go SDK、第三方网关或二次封装。

## 结论

DeepSeek Harness 与后端交流的便利程度取决于后端语言和需要的控制深度：

- **Python：方便。** 官方 Python SDK 会在本机懒启动一个同版本的 `dsh` 子进程，通过 stdio 上的换行分隔 JSON-RPC 2.0 通信，并封装了 Session、事件收集和最终回复提取。业务方不需要自行安装 Node.js。[Python SDK 说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)；[运行时 wheel 说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk-runtime/README.md)
- **Java/Go：可行，但不是开箱即用。** 官方当前提供 Python 与 TypeScript 客户端，并公开了很小的 SDK stdio JSON-RPC 协议；官方资料中未发现第一方 Java 或 Go SDK。Java/Go 可以用进程 API 启动 `dsh`，自行实现 SDK 协议或标准 ACP，也可以把 Python SDK 包在独立 worker 服务后面。[SDK 协议](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)；[ACP 服务](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)
- **没有面向普通后端的第一方长期运行 REST/gRPC Agent API。** `web` profile 确实有 `/api` HTTP/WebSocket 通道，但它属于浏览器 Web 应用的 Typert BFF/Connection 契约，依赖生成的 TypeScript 客户端、浏览器启动 token 与签名 Cookie，不应当视为稳定的跨语言公共 REST API。[API Gateway](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/api-gateway.md)；[浏览器 Connection](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/README.md)

对于本项目设想的“Vue 3 + Java/Go 业务后端 + Python agent + Docker”，推荐让 **Java/Go 负责用户、任务、队列、权限和业务持久化；Python worker 使用官方 SDK，在同一容器内通过 stdio 管理一个 DSH 子进程**。不要让浏览器直接调用 DSH，也不要把 DSH Session 当成系统唯一的任务数据库。

## 官方可用的程序化入口

| 入口 | 传输与生命周期 | 能力 | 适用场景 | 主要边界 |
| --- | --- | --- | --- | --- |
| Python SDK | Python 进程拉起 `dsh --profile sdk` 或 `sdk-minimal`；stdio JSON-RPC | 多 Session、事件与状态通知、Session 恢复、工作目录、最终回复封装 | Python agent worker、批处理 | 同步 API；没有逐 prompt 的结果对象；SDK wire 没有逐 Session close 和中途 cancel |
| TypeScript SDK | Node/TS 客户端拉起 `dsh` 子进程；stdio JSON-RPC | 与 Python SDK 同一 wire，类型最完整 | Node 服务或自定义插件宿主 | 默认解析同版本 npm `dsh`，而非 Python wheel 的 bundled runtime |
| SDK wire 自实现 | 换行分隔 JSON-RPC 2.0/stdin/stdout | 小协议，能拿到完整 DSH SessionEvent | Java/Go 自建客户端 | 协议仍是预发布状态，官方明确没有版本协商兼容承诺 |
| ACP | `dsh --profile acp`；标准 ACP v1 的 JSON-RPC stdio | Session 新建/列出/恢复/关闭、prompt、cancel、权限请求、语义化更新、每 Session 挂 MCP | Java/Go 或其他语言的自动化控制器 | `authenticate` 立即成功，即服务自身无认证；客户端必须是可信本地控制器 |
| Headless CLI | 每次启动 `dsh --profile headless`；参数或 stdin 输入，stdout 或 `--json` 输出 | 单次任务、退出码、JSON 事件流、用 `--session-id` 续接持久会话 | CI、最简单的 Java/Go 调用、低频批处理 | 一次调用只跑一个任务，进程内没有交互式 follow-up，也不是常驻服务 |
| Web `/api` | HTTP POST、WebSocket 复用；浏览器 Cookie | Web UI 的完整 Host/BFF 能力 | 官方 Web UI | 内部浏览器契约，不是推荐的后端集成面；无 Authorization bearer token |

来源：[Headless 官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.md)、[TypeScript SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/client/README.md)、[SDK server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/server/README.md)、[ACP server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)。

## Python SDK：确实是子进程，不是 Python 内嵌运行时

官方 Python 包分为两部分：

1. `deepseek-harness-sdk`：高层 `DeepSeekHarness`/`Session` API 与低层 JSON-RPC client；
2. `deepseek-harness-runtime-bin`：与 SDK 精确同版本的 `dsh` CLI 可执行文件及本地 sidecar。

安装 SDK 会安装匹配平台的运行时 wheel。`DeepSeekHarness` 第一次使用时调用 `subprocess.Popen`，连接子进程的 stdin、stdout、stderr，并启动 reader/stderr 线程；默认启动的是 `dsh --profile sdk`。这是源码可直接核实的行为：[Python client.py](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/src/deepseek_harness/client.py)、[Python api.py](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/src/deepseek_harness/api.py)。

主要生命周期语义：

- 子进程懒启动，一个 `DeepSeekHarness` 实例会跨多次 `run()` 复用它，直到 `close()` 或 context manager 退出；
- 每次启动必须显式提供 `dsh_home`，或在子进程环境中提供非空 `DSH_HOME`；Python SDK 不会自动使用 `~/.dsh`；
- `cwd` 是 agent workspace，`runtime_cwd` 是子进程工作目录，两者彼此独立；
- 正常关闭先发送 `shutdown`，再关闭 stdin；超时后才升级为 terminate/kill；
- `sdk` profile 提供完整 base 能力；`sdk-minimal` 是独立的最小组合，只保留本地执行、持久 shell、JSONL Session 等少量能力。最小组合中的 shell 可以改写运行时可见的任意路径，官方要求放在一次性 checkout 或容器中运行。[最小 SDK 示例](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/examples/README.md)

因此，“Python SDK 是不是 HTTP client”这一问题的答案是：**不是。它是本地子进程管理器加 stdio JSON-RPC client。**

## SDK stdio 协议

协议是一行一个 JSON-RPC 2.0 frame 的字节流；stdout 只能承载协议，诊断必须写 stderr。当前官方类型定义公开的方法为：[类型源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/src/types.ts)

### Client → Server 请求

- `initialize`：设置整个运行时使用的 workspace、provider、model、reasoning effort 和 max tokens；
- `session/prompt`：向指定 Session 入队一条用户消息；未知 Session id 会懒创建 Agent/Session；
- `session/resume`：恢复持久 Session，但不发送新输入；
- `session/wait`：等待已存在 Session 及其受管后代完成；
- `session/working-directory/get`、`session/working-directory/set`：查询或更改 Session 的有效目录；
- `shutdown`：刷新并关闭整个运行时。

### Server → Client 通知

- `session.event`：传送完整 `SessionEvent`；
- `session.status`：整个 Agent 的 `running`/`idle` 状态；
- `subagent.started`、`subagent.finished`：进程内子 agent 生命周期。

Session 是 append-only、event-sourced 日志，也是交互历史的唯一事实源。核心事件包含 `user/message`、`assistant/message`、`tool/call`、`tool/result`、`turn/start`、`turn/end`、请求头和上下文等，因此调用方可以从 `session.event` 做审计、进度 UI 和工具轨迹采集。[Session 参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)

但需要正确理解“run 完成”：

- `session/prompt` 返回的 `messageId` 只表示用户消息已经进入持久 inbox，不是 assistant reply id，也不是任务完成凭据；
- 高层 Python `Session.run()` 先等这个 durable receipt，再收集到该 Agent 下一次整体 `idle`，把此区间最后一个 `assistant/message` 当作 `final_response`；
- 因为期间可能有 steering、注入消息或子 agent 完成通知，`final_response` 不能严格解释为“只由这一条 prompt 唯一导致的回复”；
- SDK wire 没有中途 cancel、逐 Session close，也没有真正的 per-prompt result。放弃正在执行的 turn 时，官方 SDK 的边界是关闭整个 runtime 进程。[SDK protocol 限制](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)；[SDK server 限制](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/server/README.md)

## ACP：Java/Go 需要更强控制时更合适

`dsh --profile acp` 启动的是标准 ACP v1 的 JSON-RPC stdio server，而不是 HTTP server。一条连接可以同时运行多个相互独立的 Session；每个 Session 同一时刻只接受一个 prompt。ACP 比 SDK wire 多出以下后端友好能力：[ACP 官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)

- 持久 Session 的 `new`、`list`、`resume`、`close`；
- `session/prompt` 与 `session/cancel`；
- model、reasoning effort 配置切换；
- 语义化的 assistant/thought/tool/context 更新，而不是暴露全部 DSH 私有展示事件；
- `session/request_permission`，允许自动化控制器按自己的策略允许或拒绝一次工具操作；
- 每个 Session 可挂载 stdio 或 Streamable HTTP MCP server。

这里的 “Streamable HTTP” 指 Session 所挂 MCP server 的传输，不代表 ACP server 自身改为 HTTP。ACP server 的主入口仍是 stdio。

ACP 的关键安全语义是：`authenticate` 会立即成功，服务本身不认证调用方；官方将 ACP client 定义为可信控制器。Java/Go 服务如果采用 ACP，应该自己拥有并监督这个本地子进程，不能把 stdio 代理为未经鉴权的公网端点。权限请求也必须被客户端明确应答；不能把“前端弹窗暂时无人处理”设计成后端常态。

### Java/Go 选择建议

- **只需执行单次采集任务：** 调用 headless CLI 最简单。通过 stdin 传 prompt，使用 `--json` 消费事件，依据退出码判定进程级成功/失败。
- **需要原始 DSH 审计事件或希望与 Python SDK 语义一致：** 自行实现 SDK line-JSON-RPC。协议方法很少，但必须处理通知、请求相关性、子进程退出、stderr、超时与 stdout 污染。
- **需要 cancel、close、权限决策、MCP 或一连接多 Session：** 优先实现/采用 ACP client。
- **不建议：** 模拟 Web UI 的 `/api` 和 Cookie。该接口是 Web composition 的内部客户端契约，且当前认证只支持根页面 token 换取签名 Cookie；HTTP carrier 不接受 Authorization-header token。[浏览器认证说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/README.md)

## Web、HTTP 与 API 边界

官方 Web Host 的确提供 HTTP 与 WebSocket：Remote unary 调用映射为 `POST /api/<namespace>/<method>`，stream 使用 `/api/remote.mux` WebSocket。不过，这一层具有明显的产品内部属性：[API Gateway 参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/api-gateway.md)

- 客户端契约通过 DeepSeek 仓库构建期的 Typert code generation 生成；
- Session event stream 不是普通 Remote method，而有独立数据协议；
- Host、Origin、Cookie 和 Peer 都由 Connection 层管理；
- 启动 token 仅用于根页面或 `/connect` 的 Cookie 交换，不能作为一般 API bearer；
- 公网发布文档面向 Web UI，要求反向代理保留 Host、转发 WebSocket、正确重写 Cookie，并配置 TLS 与 `trustedHosts`。[公网部署说明](https://deepseek-harness.github.io/deepseek-harness/en/guide/public-deployments)

由这些官方事实可推导：**虽然技术上可以逆向调用 `/api`，但它不是 Java/Go 后端应依赖的公共兼容面。** 若项目需要 HTTP/gRPC，应在自己维护的 Java/Go 或 Python service 中定义稳定业务 API，再在 service 内部调用 stdio worker。

## 并发、持久化与部署边界

### 同一进程内

- SDK server 会按 `sessionId` 创建一个 Agent；JSON-RPC 请求可以并发派发，并且多个请求可以继续向同一个 Session 入队。[SDK server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/server/README.md)
- ACP 明确支持一条连接同时运行多个独立 Session，但同一 Session 的 prompt 串行。[ACP server](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)
- Python 高层 SDK 是同步 API。源码内部使用 reader thread、queue 和锁来复用 transport，但官方没有承诺 `DeepSeekHarness` 高层对象可被任意多线程并发调用。**工程推断：** 后端应按 Session 串行调度；不要把同一 Python SDK 对象的并发 `Session.run()` 当作公开保证。
- SDK 的 Session 事件通知覆盖同一 runtime 中的所有 Session，客户端再按 Session/子 agent lineage 过滤。事件消费者必须持续排空通知，避免业务层自己形成无界积压。

### 跨进程与持久化

官方 Session persistence 使用 append-only 日志，并通过 per-session handle 实施 single-writer ownership；同一 Session 已有 write owner 时，另一个 write open 会拒绝。`flush()` 才是明确的 durability barrier，正常 Session dispose/进程 shutdown 会执行最终 drain。[Persistence 参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)

这意味着：

- 可以把不同 Session 分给不同 worker，但同一个 Session 不能同时被两个 runtime 恢复并写入；
- runtime 被强杀时只保证已经跨过 durability barrier 的前缀，宿主必须区分“进程退出”“turn 失败”和“任务业务失败”；
- 官方 SDK 明确建议使用新的 Harness home 隔离 profile、插件、凭据、设置与 Session 资源。多租户部署不要共享一个全局 `DSH_HOME`。

### 推荐并发单元

最稳妥的并发单元是 **一个受监督的 DSH 子进程/容器对应一个 worker slot**，每个 slot 有独立：

- `DSH_HOME`；
- workspace；
- 临时目录与最小凭据；
- CPU、内存、网络和执行超时限制。

一个 DSH 进程内部虽然能跑多个 Session，但这些 Session 共享进程、插件树和故障域。只有在任务互相信任、资源上限已经压测、并愿意接受“一次进程崩溃影响多个 Session”时，才建议在一个 ACP/SDK runtime 中复用多个并发 Session。

## 推荐拓扑

```text
Vue 3
  │ HTTPS / WebSocket（项目自己的稳定 API）
  ▼
Java 或 Go 控制面
  ├─ 用户认证、项目权限、配额
  ├─ 任务状态机、调度、取消、重试、幂等键
  ├─ PostgreSQL：任务、来源、引用、运行索引
  ├─ 对象存储：网页快照、论文、抽取结果
  └─ 队列
       │
       ▼
Python worker（每个并发 slot 一个容器）
  ├─ 资料源 connector / 解析 / 去重
  ├─ 官方 DeepSeekHarness Python SDK
  └─ 本地 stdio JSON-RPC
       │
       ▼
DSH 子进程（独立 DSH_HOME + workspace）
```

该拓扑下，Java/Go 与 Python worker 之间可以使用团队已有的队列、内部 HTTP 或 gRPC；这是本项目自己的稳定协议。DeepSeek Harness 的预发布 wire 被限制在 worker 容器内部，升级时只需要修改 Python adapter，而不影响前端和业务后端。

建议 adapter 将 DSH 事件归一化为本项目自己的少量事件，例如 `run_started`、`progress`、`tool_started`、`tool_finished`、`artifact_created`、`run_finished`、`run_failed`。原始 `SessionEvent` 可作为审计附件保存，但不应直接成为前端或数据库的长期公共 schema。

如果坚持 Java/Go 直接管理 DSH，可采用：

```text
Java/Go worker supervisor
  ├─ 每个 slot 拉起 dsh --profile acp
  ├─ stdio ACP client
  ├─ Session → job 映射与每 Session 串行锁
  ├─ permission request 策略
  └─ 进程重启、stderr、超时与日志采集
```

ACP 比 SDK wire 更适合这个方案，因为它原生提供 cancel、close 和权限应答；如果必须取得完整 DSH raw events，则改用 SDK wire，但要接受整个 runtime 级取消边界。

## 风险与上线门槛

1. **软件成熟度。** 官方明确称其为 experimental developer preview，未经过安全审计，不能视为 production-ready。[SAFETY.md](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)
2. **协议兼容性。** SDK 协议握手没有真正的协议版本协商，官方不承诺预发布阶段兼容性。必须锁定 DSH、Python SDK 与 runtime wheel 的精确版本，并做契约测试。
3. **执行权限。** Harness 能执行模型生成的命令、加载插件并访问进程可见的文件、网络和凭据。内置 sandbox 是同内核、同文件系统的“same-world confinement”，不是真正的租户隔离；官方建议使用容器、microVM 或远程 executor。[Sandbox 说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox/README.md)
4. **认证边界。** SDK/ACP 是本地 stdio 信任模型；ACP 自身不认证。Web 的启动 token/Cookie 也不是团队级账号、租户或 RBAC。用户身份与资源授权必须由控制面实现。
5. **取消语义。** SDK wire 没有单 Session cancel/close；超时处置往往意味着终止整个子进程。需要细粒度取消时使用 ACP，或采用一任务一进程。
6. **完成语义。** SDK 的 message receipt、Agent idle、turn end 和业务任务成功是不同概念。控制面应以 `turn/end.reason.kind`、进程状态和业务校验共同决定任务结果。
7. **共享故障域。** 同一 runtime 的 Session 共享插件和进程资源。实验室多人任务应优先按用户/项目/任务做容器与 `DSH_HOME` 隔离，而不是依赖一个长寿命全局进程。
8. **可观测性。** stdout 是协议通道，任何 stdout logger 都可能破坏 framing；进程诊断只能走 stderr。必须分别采集两条流，并监控事件消费延迟、队列长度、Session 结束原因和 worker 重启次数。

## 最终判断

- 若“agent 端用 Python”已经确定，**官方 Python SDK 是当前最省事、最符合官方路径的集成方式**。
- Java/Go 与 Harness 并非无法交流，但官方没有对应语言 SDK，便利度属于“协议简单、工程工作明确”，而非“引入依赖即可用”。
- 若 Java/Go 只做控制面，优先通过项目自己的队列/API 调 Python worker；若必须直连，优先 ACP；一次性低频任务可使用 headless。
- 不建议把 Web `/api` 当公共后端 API，也不建议把一个共享 DSH Web/SDK 进程当作实验室多租户执行平台。
- 在完成版本锁定、容器隔离、权限策略、超时/取消、事件归一化和故障恢复压测前，只适合作为内部 PoC 或受控实验室工具，不应直接承载不可信用户任务。
