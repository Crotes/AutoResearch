# Pi Runtime Adapter

`WorkerRuntime` 的 Pi RPC Adapter 已实现于 `src/autoresearch/adapters/pi/`（按 `docs/development.md` 的目录边界，Adapter 代码归属 `adapters/`）。本目录只保留 Pi 相关的说明与运行约定。Pi 的 JSONL、Session 和进程生命周期不能泄漏到领域或应用模块。

## 固定版本

- npm 包：`@earendil-works/pi-coding-agent`，固定版本 **1.4.0**（`PI_PINNED_VERSION`，见 `adapters/pi/protocol.py`）。
- 安装：`npm i -g @earendil-works/pi-coding-agent@1.4.0`，用 `pi --version` 核对。
- 升级前必须重跑 `tests/contracts/` 与 `tests/fixtures/pi/` 的协议 fixture 测试。

## 运行约定

- 一个 ResearchRun 对应一个 `pi --mode rpc` 子进程；原始协议记录全量写入 `.autoresearch/sessions/<run_id>/pi-events.jsonl`（审计附件，不进入 Git）。
- `agent_settled` 只表示当前 Pi 工作回合结束；Application 工作流随后进入选源或终审检查点，只有人工审核决定可以推动 ResearchRun 完成。
- Windows 上通过 `shutil.which("pi")` 解析 `pi.cmd`（CreateProcess 不做 PATHEXT 查找）。
- 模型接入：自定义端点配置在用户级 `~/.pi/agent/models.json`（注意是 `agent/` 子目录），`apiKey` 支持 `$ENV_VAR` 插值，凭据不写入仓库。
- 项目级 `.agents/skills/` 需要 `--approve` 信任；AutoResearch 的版本化事实源位于 `skills/`，运行时用 `--skill skills/<name>` 显式加载（`tests/fixtures/pi-skill-project/` 为最小 Skill 样例）。
- 已知环境限制：Pi 在 Windows 上按系统代码页读取 Skill 文件，非 ASCII 内容会乱码，Skill 文件暂用英文书写。
