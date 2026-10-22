# AutoResearch 架构概览

AutoResearch 采用 Skill-first 混合架构：确定性模块保证状态和数据正确性，Tools 提供受控外部能力，Skills 承担需要研究判断的行为。Pi 是可替换的 Worker Runtime，而不是业务事实源。

## 运行拓扑

```text
CLI
  │
  ▼
Application
  ├─ Workflow
  ├─ Review
  ├─ Repository
  ├─ Export
  └─ WorkerRuntime interface
       │
       └─ PiRuntimeAdapter
            │ JSONL RPC
            ▼
          Pi process
            │ MCP
            ▼
      research-tools server
        ├─ SourceAcquisition
        ├─ ContentProcessing
        ├─ IdentityResolution
        ├─ LibrarySearch
        └─ ArtifactSubmission
```

SQLite 和本地文件系统是 PoC Adapter。模块接口不暴露其实现细节，以便内部 Alpha 替换为 PostgreSQL、对象存储和队列。

research-tools MCP Server 已实现于 `src/autoresearch/adapters/mcp/`（stdlib stdio JSON-RPC，保持运行时零依赖），向 Skills 暴露六个受控 Tool；安全边界见 `tools/research_tools/README.md`。

## 深模块与 seam

### Workflow 模块

解释版本化工作流、执行状态转换、保存检查点、处理重试和人工审核。Skill 不能直接改变其状态。

### WorkerRuntime 模块

隐藏 Pi 子进程、RPC framing、Session、事件映射和异常退出。生产使用 `PiRuntimeAdapter`，测试使用内存 Adapter。

### SourceAcquisition 模块

隐藏各来源的认证、查询、分页、限流、缓存和许可规则。调用者只发现候选或物化来源文档。

### ContentProcessing 模块

隐藏下载、格式检测、正文提取、规范化、分块、内容哈希和证据定位。

### ResearchLibrary 模块

负责成果身份、来源版本、工件版本、审核记录、索引与派生失效。

### ArtifactSubmission 模块

验证 Agent 的结构化输出，拒绝非法或缺少证据的工件，并在事务中写入资料库。

## 依赖方向

```text
CLI → Application → Domain
                   ↑
Adapters ──────────┘
```

领域模型和应用模块不依赖 Pi、MCP、SQLite、HTTP 或具体来源 SDK。Adapter 依赖相应外部协议并满足模块接口。

## 领域事件

- `run.started`
- `step.started`
- `source.discovered`
- `source.materialized`
- `artifact.created`
- `review.requested`
- `step.failed`
- `run.cancelled`
- `run.completed`

Pi 原始事件可以作为审计附件保存，但不得成为 CLI、未来前端或数据库的稳定接口。

## 仓库目标布局

```text
/apps
  /cli
  /web
/runtime
  /pi
/workflows
/skills
/tools
/packages
  /domain
  /storage
/evals
/infra
/docs
```

PoC 只创建实际需要的目录，不为未来结构预先生成空包。
