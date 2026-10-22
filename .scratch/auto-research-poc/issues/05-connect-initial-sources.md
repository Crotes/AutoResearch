# 接入首批资料来源

Type: task
Status: claimed
Owner: Kimi
Blocked by: 01, 04

## 目标

通过 `SourceAcquisition` 模块接入 arXiv、GitHub、RSS/Atom 和手动 URL。

## 范围

- 查询、分页、限流、缓存和重试
- URL 规范化和来源元数据统一
- GitHub 仅处理约定范围的仓库资料
- RSS/Atom 仅处理白名单 Feed
- 手动 URL 遵守访问和保存策略

## 验收

- 四类来源输出统一 Candidate 和 SourceRef
- 单个来源失败不影响其他来源
- 限流与不可重试错误可区分
- 网络集成测试可用录制 fixture 离线运行

## Comments

- 2026-10-22：已实现 `adapters/sources/` 子包（http/normalize/arxiv/github/rss/manual/composite）。`license_access_policy` 共享映射落在 `normalize.py`；测试替身为 `tests/unit/fake_http.py`（脚本化 FakeTransport + FakeClock）。
- 设计要点：Transport 可注入，测试全离线；RSS 白名单默认空（未配置即拒绝一切 feed）；手动 URL 拒绝内网地址（SSRF 防线）；GitHub token 仅从 `GITHUB_TOKEN` 环境读取。

## Answer

实现：四类来源连接器统一输出 `Candidate`/`SourceRef`；HTTP 层含超时、`Retry-After` 感知退避重试、per-host 令牌桶限流、`.autoresearch/cache/` 文件缓存（TTL 24h）；物化时按 ADR-0005 映射访问策略并记录 SHA-256 与抓取时间。错误分类：429/5xx/网络→transient（可重试），401/403→policy，404/410→permanent，解析失败→content；`discover_with_failures()` 暴露单源失败而不中断其他来源。

验证结果：

- `pytest` 140 项通过（新增 45，全部离线运行，fixture 为人工构造样例）；Ruff 检查与格式检查通过；mypy strict 通过；`autoresearch demo` 正常。
- 验收对照：四类来源统一 Candidate/SourceRef ✅；单源失败隔离 ✅；限流（transient）与不可重试（permanent/policy/content）可区分 ✅；网络集成测试全部经录制 fixture 离线运行 ✅。

任务验收四条均满足，待 PR 评审合并后转为 `resolved`。
