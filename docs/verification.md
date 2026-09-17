# 第一阶段验收记录

> 此页保留早期阶段证据。v0.1.0-preview.1 的最终验收结论见 [Release Candidate 报告](release-candidate-report.md)。

2026-09-15。

## 已执行

- Windows Python 3.12：19 项 pytest 测试通过。
- 实际 Ubuntu 24.04.2 服务器的 Linux Python 3.12 容器：同一组 19 项测试通过。
- 两端 pip check：无依赖冲突。
- 前端 TypeScript 检查及 Vite 生产构建通过。
- 本地、SSH 隧道到实际服务器、公网 HTTPS 三种访问路径的 Chrome/Playwright 浏览器验收通过：登录、测试供应商新增与删除、API Key 遮蔽、Local 创建/读写/清理、子代理列表、390px 手机布局、无控制台错误。测试供应商已删除。
- 实际容器重启后管理 API、默认 Agent 配置、Dashboard 和 Local Sandbox 探测正常。
- 域名解析为 47.77.219.0；Caddy 已获得 Let's Encrypt 证书，HTTPS 健康接口返回正常。
- `.env`、data（含管理员令牌）、虚拟环境、依赖目录和测试截图均被 Git 忽略。未创建 Git 提交或推送。

## 限制与已知提示

- 未提供真实模型或 Shipyard 凭据；模型与 Bay 协议测试使用 MockTransport/Fake Provider。未声称完成真实模型推理或远程 Sandbox 执行验证。
- pytest 有两条上游弃用提示（Starlette 测试客户端 httpx 兼容层、AnyIO BlockingPortal 别名），未影响测试结果。
- 当前不是完整自动维护系统：工作流与无人值守可靠性功能见 architecture.md。

## 第二阶段候选版本（2026-09-15）

- Windows 与实际 Linux v0.2 镜像均通过 35 项 pytest；前端 TypeScript/Vite 生产构建通过，`pip check` 无依赖冲突。
- OpenHands SDK adapter 实际构造 Conversation 并成功加载 3 个任务唯一工具；无可用模型 Endpoint 的探测按预期进入统一运行错误。
- 线上数据库升级前完成 SQLite 在线备份与 `.env` 备份。源库和备份均通过 `integrity_check`，逐表行数一致；升级后 schema migration 为 2，原 5 个 Agent 和 3 项配置保留。
- 实际服务器运行 `ai-maintainer:0.2.0`，Compose 两个服务 healthy，公网 HTTPS `/healthz` 正常；管理 API 报告 GitHub automation 阶段和 OpenHands 1.47.0。
- 公网静态 HTML 已引用 v0.2 构建；GitHub 配置 API 不包含 `private_key` 或 `webhook_secret` 原文字段，仓库与任务当前为空。
- Windows Computer Use helper 无法建立 Node kernel；本机 Chrome headless 在当前托管环境异常退出。因此本轮以真实 HTTPS 静态资源与认证管理 API 验证替代视觉浏览器检查，不能把它表述为已完成的浏览器交互验收。
- 真实 GitHub App、模型、Shipyard 和 SMTP 尚未配置。完成专用测试仓库的 Issue→PR、PR request changes→复审→approve 与邮件投递前，第二阶段仍为候选版本。

## 公网白屏修复（2026-09-15）

- 公网入口 HTML 为 200，但其 JS/CSS 均返回 401 JSON；服务器回环请求复现同一结果。
- 根因是 SCP 上传后的 `frontend/dist/assets` 保留了 root 限制权限，镜像以 UID 10001 运行时无法读取。Starlette StaticFiles 将 `PermissionError` 映射为 401，导致浏览器无法启动 React。
- Dockerfile 现使用 `COPY --chown=maintainer:maintainer` 并显式设置静态目录可读/可遍历权限；静态 mount 也固定在认证 API router 之前。
- 新增回归测试验证匿名访问入口、JS、CSS，检查 200、JavaScript/CSS MIME 和非认证响应。入口 HTML 使用 `no-store`，哈希资源使用一年 immutable 缓存，避免版本错配。
- 修复镜像在 Linux 通过 36 项测试。公网 JS 为 200 `text/javascript`、256301 bytes；CSS 为 200 `text/css`、9399 bytes。
- 全新 Playwright Chrome context 从公网 HTTPS 验证登录控件可见，并使用本地私有令牌完成登录；Dashboard 与 GitHub 接入导航可见，Console error 和 failed request 均为 0。
