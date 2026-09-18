# v0.1.0-preview.2 Preview Release

Maintune 是面向 GitHub 仓库的自托管维护代理。它已经能把 Issue 分析、受控代码修改、测试、独立审核、PR 审核与确定性自动合并串成可追踪闭环，并提供以 `#66CCFF` 为主色的天依风格默认界面、九步 Setup Wizard 和部署运维工具。

## 已验证

- Plugin API v1、本地 `.mtp` 插件包、capability 权限控制和加密插件 Secret；
- 插件 enable / disable / reload、README 安全查看、ACK 与 replay protection；
- AstrBot Bridge 外置插件的通知、查询和结构化 Owner Decision 闭环；
- GitHub Issue → PR → Review → Merge 基础闭环；
- 外部贡献者 PR 的 Request Changes → synchronize → re-review → Approve；
- Controller/Policy 执行 GitHub 写操作，模型只提供建议；
- Local Sandbox 与 Shipyard Neo；
- OpenAI-compatible Provider 与 OpenHands Runtime；
- Timeline 失败原因、Token 使用、诊断、备份和恢复；
- 功能、高风险、缺少信息与非维护请求的确定性 Triage Gate；
- 中文与英文 WebUI、语言持久化和双语 Setup Wizard；
- Ubuntu 24.04、本地 Docker Compose 构建和桌面/手机 Chrome 流程。

## Preview 边界

- 插件系统为 **Experimental**，其能力、界面、配置结构和扩展 API 仍可能变化；
- Local Sandbox 不是强安全隔离，不适合直接执行不可信仓库；
- 自动修复成功率取决于仓库、测试、模型和 Policy，仍需维护者监督；
- Windows 11 脚本已经过静态与流程检查，Docker Desktop fresh-install 的最终人工验收尚未闭环；
- **不提供预构建 GHCR 镜像。** 当前版本通过源码 Release Bundle 在用户机器本地构建，以避免重新分发许可边界尚未解决的传递 Runtime 工件；
- 不支持完整离线安装。

本版本的完整变更见 [v0.1.0-preview.2 Release Notes](releases/v0.1.0-preview.2.md)。

## 默认视觉与素材

默认 UI 直接采用天空蓝、薄荷、白色和少量粉紫的轻量主题。页面使用本项目生成的洛天依二次元立绘和十个 Q 版导航图，没有打包第三方官图或来源不明的搬运图。角色权利不随 AGPL 代码许可授予；详细边界见 [界面素材与授权](licensing/asset-attribution.md)。

## 适合谁试用

适合愿意自己部署、能配置 GitHub App 与模型、会审阅自动化 Policy，并希望为少量仓库试验维护闭环的个人或小团队。请先在专用测试仓库验证，再逐步接入真实仓库。

## 发布说明模板

本次 Preview 提供源码 Release Bundle、安装/升级/备份/恢复脚本、Setup Wizard 和完整部署文档。它展示了 Maintainer 当前已经可运行的闭环。插件系统仍为 Experimental；Windows 11 + Docker Desktop fresh-install 仍属于人工验证项；本版本不提供公共预构建 GHCR 镜像，也不支持完整离线安装。

源代码使用 AGPL-3.0-only；AGPL 本身允许在遵守其条款时商业使用。如需闭源、专有集成、OEM 或其他替代条款，可与 mcxianyujun 单独签订 Commercial License。本项目原创/生成的洛天依二创视觉素材，在项目作者拥有或控制的权利范围内使用 CC BY-NC-SA 4.0。洛天依 / VSINGER 的角色名称、设定、形象及底层 IP 不在上述授权范围内，相关权利归其权利方。第三方依赖继续遵循各自许可证。外部贡献不会仅因提交 PR 而自动进入商业再许可范围；双授权核心贡献需另行完成 CLA。
