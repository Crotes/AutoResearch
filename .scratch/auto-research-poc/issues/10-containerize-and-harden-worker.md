# 容器化并收紧 Worker 权限

Type: task
Status: ready-for-agent
Blocked by: 03, 04, 09

## 目标

使用 Docker 隔离每项活动研究运行，并验证取消、资源限制和秘密管理。

## 范围

- 非 root、只读基础镜像和独立可写 workspace
- 域名白名单、最小凭据和 Secret 注入
- CPU、内存、磁盘、进程、下载大小和执行时间限制
- 一任务一 Pi RPC 进程
- 取消、异常退出和清理

## 验收

- Worker 无法读取未挂载的宿主资料
- API Key 不出现在 Git、工件和 Session 日志中
- 取消任务会终止 Pi 及其子进程
- 恶意网页指令不能扩大 Tool 权限

## Comments
