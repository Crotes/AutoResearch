# AutoResearch PoC 产品规格

Status: accepted

## 1. 目标

为实验室内部研究者构建一个 Skill-first 的资料收集与分析 PoC。系统针对“Agent 的自进化”等研究主题，从受控来源发现成果，形成可审核、可追溯的三层研究结果，并验证该流程是否显著降低人工速览成本。

## 2. 首要用户

- 3–5 人实验室团队中的研究成员
- 研究成员创建研究项目和运行、筛选候选成果并复核证据
- 审核者决定哪些成果进入共享资料库
- PoC 不实现账号系统，默认运行环境中的操作者是可信实验室成员

## 3. 核心场景

研究者创建一个研究运行，填写核心问题、包含与排除关键词、时间范围、语言、来源范围和可选种子资料。系统扩展中英文查询，在人工确认后从 arXiv、GitHub、RSS/Atom 白名单和手动 URL 发现资料。

系统先完成成果级去重和粗筛，为全部候选生成速览。研究者选择值得深入的成果后，系统生成证据化详细解读，并仅基于这些成果生成分类总结。审核通过的成果与工件进入共享资料库。

## 4. 三层输出

### 4.1 速览

- 一句话结论
- 与研究问题的关系
- 来源、作者、日期与原始链接
- 主题相关性、来源可信度、证据强度、新颖性、时效性、可复现性和潜在价值
- 关键标签和失败警告

### 4.2 详细解读

- 研究问题与背景
- 方法、系统或算法
- 实验设置、数据和基线
- 核心结果
- 局限与适用条件
- 可复现性与代码状态
- 与 Agent 自进化的关系
- 每项重要结论对应的证据位置

### 4.3 分类总结

- 预定义类别与本次涌现类别
- 方法谱系与成果比较
- 共识、冲突和证据缺口
- 研究空白与值得继续追踪的问题
- 对每项判断的成果与证据引用

## 5. 工作流

```text
创建研究计划
→ 人工确认查询扩展
→ 发现候选来源
→ 物化正文并进行成果级去重
→ 粗筛与多维评分
→ 为所有候选生成速览
→ 等待人工选择
→ 为选中成果生成详细解读
→ 生成分类总结
→ 等待最终审核
→ 收录并导出
```

工作流通过版本化 YAML/JSON 描述，由确定性状态机解释。Skill 可以在步骤内部创建子任务或追加检索，但不能跳过审核、改变顶层流程或扩大权限。

## 6. 来源范围

PoC 自动接入：

- arXiv
- GitHub 仓库元数据、README、指定文档、Release 和显式指定文件/Commit
- 实验室维护的 RSS/Atom 白名单
- 用户手动提交的公开 URL

PoC 不接入：

- 小红书、抖音、Bilibili 自动搜索或抓取
- Crossref、会议官网和通用全网爬虫
- GitHub 全量 Issue、PR、Discussion 和评论

## 7. 全文与权限

- 公开许可、实验室有权使用或成员合法上传的内容可保存全文
- 许可不明确的内容不得默认批量归档
- 不绕过登录、付费墙、验证码、访问控制或反爬机制
- 每个来源版本记录来源、抓取时间、内容哈希、许可与访问级别
- 删除来源版本时，删除其索引并标记依赖工件过期

## 8. 数据模型

- `ResearchProject`：长期研究主题
- `ResearchRun`：一次有状态执行
- `ResearchPlan`：经确认的检索输入
- `Work`：独立研究成果
- `SourceVersion`：成果的具体来源和版本
- `SourceDocument`：规范化、分块后的内容
- `Evidence`：可定位的支持材料
- `Artifact`：不可变的速览、详细解读或分类总结
- `ReviewDecision`：追加式人工判断
- `SkillVersion`：生成结果所用 Skill 版本

同一成果的预印本、正式论文、代码仓库、博客和视频讲解关联到同一个 `Work`，但保留独立 `SourceVersion`。

## 9. 架构约束

- Python 实现 PoC 控制程序、工作流、来源连接器和 MCP Tools
- Pi `pi-coding-agent` RPC 是唯一 Agent Runtime
- 不使用 Pi Durable
- 每项活动研究任务使用独立 Pi 进程、工作目录和容器
- SQLite 保存结构化数据，本地受控文件系统保存全文与工件
- Agent 只能通过白名单 MCP Tools 操作，不直接写业务数据库
- 所有 Skill 输出 JSON、Markdown、证据、警告和 Skill 版本
- Pi 原始事件只作审计附件；前端与业务存储使用本项目领域事件

## 10. 模块接口

### WorkerRuntime

```text
start(runSpec) -> runId
events(runId, cursor) -> events
cancel(runId)
resume(runId)
inspect(runId) -> status
dispose(runId)
```

### SourceAcquisition

```text
discover(researchPlan) -> stream<Candidate>
materialize(sourceRef) -> SourceDocument
```

### research-tools MCP

```text
discover_sources
materialize_source
search_library
read_source_chunks
submit_artifact
request_human_review
```

## 11. Skills

- `plan-research`
- `collect-sources`
- `triage-sources`
- `analyze-source`
- `synthesize-topic`
- `verify-evidence`

每个内部 Skill 包含输入/输出 Schema、测试用例、预期结果、变更记录；改自第三方时还需记录上游仓库、提交、许可证和本地修改。

## 12. 安全与可靠性

- 网页、论文、README 和评论均视为不可信数据，不得改变 Agent 指令或权限
- API Key、Cookie、数据库凭据和内部资料不得进入 Skill、Git 或 Session 日志
- 每一步完成后保存检查点
- 每次运行具有时间、Token、费用、轮次、候选数量和无新增成果等停止条件
- 错误分类为 `transient`、`permanent`、`content`、`model`、`policy` 和 `internal`
- 单一来源失败不能导致整次运行失败

## 13. PoC 操作入口

```text
autoresearch project create
autoresearch run start
autoresearch run status
autoresearch run events
autoresearch run review
autoresearch run resume
autoresearch run cancel
autoresearch run export
```

## 14. 验收标准

- 使用 3–5 个真实“Agent 自进化”问题完成运行
- 一次运行在预算内返回至少 20 条候选，人工相关率目标不低于 80%，重复项目标低于 10%
- 所有候选具有速览；人工选中的成果具有详细解读；运行具有分类总结
- 大多数重要结论能正确定位到原始证据
- 人工审核、追加式反馈和导出可用
- 进程中断后可以从最近检查点恢复
- 来源失败、限流、正文缺失和解析失败均可诊断
- 能记录耗时、Token、费用、错误和人工质量判断

## 15. 明确非目标

- Vue 前端
- Java/Go 控制面
- 登录、RBAC 和多租户
- 定时增量监控与通知
- 自动产生研究 Idea
- 自动修改或部署 Skill
- 多模型协作
- 独立向量数据库
- 公网部署

## 16. PoC 后决策

PoC 质量达标后，再决定 Java 或 Go 控制面、Vue 工作台、PostgreSQL、对象存储、队列、登录权限、增量调度、更多来源和 Idea 支持。若连续三轮迭代仍无法改善相关性、证据完整性或人工节省时间，应暂停平台功能扩张并重新检查来源、问题表达、Tool 与 Skill 设计。
