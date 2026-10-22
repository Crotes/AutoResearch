# 修复任务 03–06 评审发现

Type: task
Status: claimed
Blocked by: 03, 04, 05, 06
Owner: Codex

## 目标

修复任务 03–06 代码审查发现的访问策略、审核门、安全校验、证据归属、身份解析和分页问题。

## 范围

- 在缓存和正文暴露前执行访问策略
- 让 Pi Runtime 服从工作流人工审核门
- 对 HTTP 重定向与解析地址执行域名和 SSRF 校验
- 验证工件证据属于当前运行的真实来源分块
- 正确移除 arXiv 末尾版本号并解除 Application → Adapter 依赖
- 实现 GitHub 搜索分页
- 修正任务 05 生命周期状态

## 验收

- 每项缺陷都有失败先行的自动化回归测试
- metadata-only/controlled 正文不缓存、不注册、不返回
- Pi 执行结束不会自动跳过人工审核
- 重定向和内网解析不能绕过来源策略
- 伪造或跨运行证据被拒绝
- 旧式 arXiv ID 不发生身份碰撞
- GitHub 可读取多页且受候选上限约束
- 完整测试、Ruff、格式检查和 mypy strict 通过

## Comments

- 2026-10-22：建立目标回归环，初始结果为 `11 failed, 70 passed`，分别复现缓存越权、审核门绕过、重定向未复核、伪造证据、arXiv 身份碰撞、GitHub 不分页和 Application 反向依赖。
- 任务 07 的未提交 Skill 目录与 `tools.py` 修改已按用户要求撤销；原 `feat/07-core-research-skills` 分支保留为历史指针，修复在 `fix/14-review-findings` 分支进行。
- 2026-10-22：修复已提交并创建 PR #5，等待非作者评审与合并。

## Answer

实现已完成并提交至 PR #5，等待评审和合并后转为 `resolved`：

- HTTP 支持按请求禁用缓存，并手动跟随、逐跳复核重定向；Manual URL 同时校验域名、字面 IP 与 DNS 解析结果。
- metadata-only/controlled 来源不再把正文放入 `SourceDocument`，物化请求不缓存未知许可正文；GitHub 在确认开放许可证后才读取 README/Release。
- Pi 的 `agent_settled` 仅结束当前 Worker 回合，ResearchRun 依次进入选源和终审检查点；恢复由纯工作流状态机校验。
- MCP 工件提交验证每个证据锚点属于当前 Run 已物化且真实存在的分块。
- arXiv 仅移除末尾 `v<数字>`，旧式 `solv-int/...` 不再碰撞；URL 规范化移入 Domain，解除 Application → Adapter 依赖。
- GitHub 搜索实现有界分页；任务 05 状态改为 `resolved`。
- 额外修复 Pi watchdog 与已关闭 stdin 竞争产生的线程异常。

验证结果：`pytest -W error` 179 项通过，Pi 并发集成测试连续三轮各 11 项通过，Ruff 检查与格式检查通过，mypy strict 通过，`git diff --check` 与离线 demo 通过。
