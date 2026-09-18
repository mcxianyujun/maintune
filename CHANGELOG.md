# Changelog

## 0.1.0-preview.2 - Plugin API v1

- 新增进程外 Plugin API v1，以及经过校验的本地 `.mtp` 插件包安装流程。
- 新增插件 enable、disable、reload 生命周期和进程崩溃隔离。
- 新增 capability 权限模型、加密插件 Secret、命名空间路由与安全 README viewer。
- 新增事件 ACK、断线重连、去重、Owner Decision 防重放和短任务引用。
- 重做插件管理卡片、设置对话框和 Running / Connected 状态展示。
- 通过两个独立外置插件验证 Maintune 与 AstrBot 的双向桥接。

插件接口仍标记为 Experimental。此 Preview 继续采用本地构建分发，不提供公共 GHCR 镜像。

## 0.1.0-preview.1 - Release candidate

- 首次公开 Preview 的 GitHub Issue / PR 自动维护闭环。
- 确定性 Controller policy、可观察失败事件和 Bot PR 自动合并策略。
- 高级模型、Agent Runtime、预算、超时与 Reset 配置。
- Local 与 Shipyard Neo Sandbox、OpenHands SDK 1.47.0 adapter。
- 九步 Setup Wizard、运维 Dashboard 与响应式蓝白控制台。
- 默认 `#66CCFF` 洛天依主题、二次元 Hero、Q 版导航与移动端布局。
- 本地构建式 Docker Compose、Windows/Linux 安装和运维脚本。
- Release bundle、校验和、CI、依赖/Secret 审计与 AGPL 文档。
- 源代码 AGPL-3.0-only，可与 mcxianyujun 单独协商替代 Commercial License；项目原创/生成的洛天依二创视觉素材在作者可授权范围内采用 CC BY-NC-SA 4.0。

公共预构建容器不在此 Preview 中分发。插件系统仍为 Experimental；Windows 11 + Docker Desktop fresh-install 仍属于人工验证项。
