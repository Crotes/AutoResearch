# 集成 Pi RPC Runtime

Type: task
Status: claimed
Owner: Kimi
Blocked by: 01, 02

## 目标

实现 `PiRuntimeAdapter`，用独立子进程执行 Skills，同时不向上层泄漏 Pi 协议。

## 范围

- 启动和监督 `pi --mode rpc`
- 实现 JSONL framing、请求关联、事件消费和 stderr 采集
- 映射 start、events、cancel、resume、inspect 和 dispose
- 将 Pi 事件归一化为领域事件
- 固定 Pi 版本并增加协议 fixture 测试

## 验收

- 可执行一个最小 Skill 并取得结构化结果
- 超时、异常退出、无效 JSON 和取消均产生明确错误
- 上层测试不引用 Pi RPC 类型

## Comments

- 2026-10-22：已实现 `src/autoresearch/adapters/pi/` 子包（protocol/process/events/adapter），pi 固定 1.4.0（`@earendil-works/pi-coding-agent`）。协议契约与生命周期由 fake_pi 进程替身 + `tests/fixtures/pi/*.jsonl` 固定样例覆盖，54 项测试、Ruff、mypy strict 全绿。
- 现场验收发现并修复一个正确性缺陷：模型错误（如 401/429/连接失败）重试耗尽后 Pi 仍发 `agent_settled(aborted=false)`，原先会把失败的 run 误标为 COMPLETED。现 `message_end(stopReason=error)` 与 `auto_retry_end(success=false)` 均落终态 FAILED，后续完成事件被终态保护丢弃。
- 环境适配记录：Windows 需 `shutil.which("pi")` 解析 `pi.cmd`；自定义模型端点配置在 `~/.pi/agent/models.json`（`agent/` 子目录）；项目级 `.agents/skills/` 需 `--approve`，显式加载用 `--skill <dir>`；Pi 在 Windows 按系统代码页读 Skill 文件，非 ASCII 内容乱码，fixture Skill 用英文。

## Answer

实现：`PiRuntimeAdapter`（一 run 一 `pi --mode rpc` 子进程），含严格 JSONL 分帧（仅 LF、容忍 CR）、命令 id 关联、stderr 采集、预算 watchdog、审计落盘 `.autoresearch/sessions/<run_id>/pi-events.jsonl`；Pi 事件归一化为领域事件，原始记录仅作审计附件（ADR-0003）。错误映射：spawn 失败→internal，进程中途退出/命令超时/预算超时→transient，provider 错误→model。

验证结果：

- `pytest` 54 项通过（含协议分帧、fixture 归一化、事件 schema 校验、fake_pi 全生命周期集成：start/events/resume/完成、cancel、预算超时、异常退出、无效 JSON、错误后误标完成的回归）；Ruff 检查与格式检查通过；mypy strict 通过；`autoresearch demo` 正常。
- 上层集成测试只引用 `PiRuntimeAdapter` 类本身与 ports/domain 类型，不引用 Pi RPC 协议类型。

现场验收（真实 pi + 最小 Skill）：**通过**（2026-10-22）。DeepSeek Anthropic 兼容端点 + `deepseek-flash`，`/skill:minimal` 返回期望的结构化 JSON `{"skill": "minimal", "status": "ok"}`。配置方式：仓库根 `.env`（模板 `.env.example`）提供 `PI_MODEL_ID`/`PI_MODEL_BASE_URL`/`PI_API_KEY`，验收脚本 `.autoresearch/acceptance/accept.py` 据此渲染 `~/.pi/agent/models.json` 后驱动真实 pi 子进程。

验收中发现的环境事实：pi 的 `models.json` 仅 `apiKey` 支持 `$ENV` 插值，`baseUrl` 不插值，故由脚本渲染；此前曾遇 `api.deepseek.com` 连接重置与 Moonshot 账户暂停，均为环境问题而非实现缺陷。

任务验收三项均已满足，待 PR 评审合并后转为 `resolved`。
