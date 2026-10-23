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

 Application 层的编排深模块是 `ResearchWorkflow`（`application/research.py`）：CLI 只做输入与展示，工作流状态、审核规则、恢复、事件持久化和导出都集中在这里。采用「前台执行到稳定检查点」的模型（ADR-0008）——`start`/`resume` 阻塞到审核闸门或终态，状态写回 SQLite 后关闭 Pi 进程；下一次 CLI 调用从 SQLite 重建运行上下文并恢复，Pi Session 仅作执行上下文。工件提交策略包装器（`application/artifact_policy.py`）在 MCP 提交前强制「只分析选中成果」「分类总结只引用选中成果及其证据」，不依赖 Skill 自觉。

 SQLite 和本地文件系统是 PoC Adapter。`SqliteResearchLibrary` 保存项目、运行、成果、来源版本、证据、工件、审核决定、完整 `RunSpec` 和领域事件；FTS5 提供工件检索，正文按访问策略写入内容寻址目录。模块接口不暴露其实现细节，以便内部 Alpha 替换为 PostgreSQL、对象存储和队列。`ResearchWorkflow` 是唯一写领域事件的方，按 `(run_id, sequence)` 幂等落库，跨进程恢复时重复 drain 不产生重复事件。

research-tools MCP Server 已实现于 `src/autoresearch/adapters/mcp/`（stdlib stdio JSON-RPC），向 Skills 暴露六个受控 Tool；工件提交使用 `jsonschema` 校验对应 Skill 的版本化输出契约，安全边界见 `tools/research_tools/README.md`。

## 深模块与 seam

### Workflow 模块

解释版本化工作流、执行状态转换、保存检查点、处理重试和人工审核。Skill 不能直接改变其状态。

`application/workflow.py` 是纯函数状态机（`transition(WorkflowSnapshot, WorkflowAction)`），强制两道人工审核门：选源（`overviews_ready` 检查点）与终审（`analyses_ready` 检查点）。`ResearchWorkflow` 复用该状态机做每次操作前的合法性校验，`run resume` 在未选源、未终审通过或已终态时会拒绝执行。探索模式的顶层流程定义在 `workflows/exploration-v1.json`，由契约测试保证其与状态机检查点/审核门一致。

### WorkerRuntime 模块

隐藏 Pi 子进程、RPC framing、Session、事件映射和异常退出。生产使用 `PiRuntimeAdapter`，测试使用内存 Adapter。

### SourceAcquisition 模块

隐藏各来源的认证、查询、分页、限流、缓存和许可规则。调用者只发现候选或物化来源文档。

PoC 已实现四类连接器（`adapters/sources/`）：arXiv Atom API、GitHub REST（元数据/README/Release）、RSS/Atom 白名单、手动 URL；统一输出 `Candidate`/`SourceRef`，单源失败隔离，HTTP 层具备限流、退避重试与文件缓存，许可按 ADR-0005 映射访问策略。

### ContentProcessing 模块

隐藏下载、格式检测、正文提取、规范化、分块、内容哈希和证据定位。

PoC 已实现于 `application/content/`：HTML/PDF/Markdown/纯文本检测（PDF 为 stdlib 最小提取，失败降级为 content 错误），结构感知分块产生稳定锚点（`<source_version_id>#chunk-<N>`，PDF 附页码），相同内容重复处理完全幂等；访问策略为 `metadata_only`/`controlled` 时正文不进入提取路径（ADR-0005 的结构性保证）。成果身份解析与人工 merge/split 纠错在 `application/identity.py`（ADR-0004）。

### ResearchLibrary 模块

负责成果身份、来源版本、工件版本、审核记录、索引与派生失效。公开读取 seam 可在进程重启后重建项目、运行（含检查点）、成果、来源、工件及审核选择；SQLite 连接由 Adapter 串行化访问，可安全承接 MCP 的线程池调用。

### ArtifactSubmission 模块

按产出 Skill 的 `output.schema.json` 验证 Agent 结构化输出，拒绝非法、缺少证据或依赖失效工件的提交，并在事务中写入资料库。

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
