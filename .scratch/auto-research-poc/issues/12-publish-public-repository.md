# 发布公共 GitHub 仓库

Type: task
Status: ready-for-human
Blocked by: 01, 10, 11

## 目标

在确认数据隔离和供应链信息后，将代码作为 Apache-2.0 公共仓库发布。

## 范围

- 初始化 Git 与公共 GitHub 仓库
- Apache-2.0、README、贡献说明和安全说明
- GitHub Issues、Projects 和分支保护
- 第三方 Skill 来源、许可证与修改记录
- 忽略规则、Secret 扫描与脱敏示例复核

## 验收

- 仓库不包含全文、真实研究任务、成员反馈、Session、日志或凭据
- main 分支受保护，Pull Request 必须通过 CI
- 外部 Issue/PR 可提交，但路线和合并权由实验室控制
- 当前本地问题跟踪配置已切换为 GitHub Issues

## Comments

- 2026-10-22：部分范围已提前完成（未认领，仅记录进度）：
  - Git 已初始化（默认分支 `main`），初始提交与 `.gitattributes`（统一 LF）已推送至公共仓库 `https://github.com/Crotes/AutoResearch`。
  - 忽略规则复核通过：`.venv`、缓存、`.autoresearch/`、`data/`、`*.sqlite`、`.env`、`*.pem`/`*.key` 等均已排除，无私密文件进入仓库。
  - GitHub 仓库已开启 Secret scanning 与 Push protection（API 验证：`enabled`/`enabled`）。
  - `docs/collaboration.md` 已同步为启用分支/PR 并行协作。
- 剩余范围（GitHub Issues/Projects 迁移、分支保护与 CI 门禁、CODEOWNERS、安全说明、第三方 Skill 许可复核）仍受任务 10、11 阻塞，任务保持未认领。
