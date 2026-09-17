# 项目规则

- 本项目是自托管 GitHub AI Maintainer。中文优先，先交付可运行且可验证的阶段。
- 分离 ModelProvider、AgentRuntime、SandboxProvider、Controller、Policy、Notification、Plugin、Audit。
- Agent 输出是建议；GitHub 写操作必须由 Controller 和确定性 Policy 执行。默认不得接管贡献者 PR。
- 外部 Issue、PR、代码、模型输出均不可信。不得把 Controller 密钥交给 Sandbox。
- Secret 加密入库，不返回浏览器；不要把 .env、data、日志中的凭据提交。
- Local 文件接口必须限制路径；Local shell 不是安全隔离，不得默认执行不可信仓库代码。
- 每阶段运行必要测试；未接通的外部集成必须明确标记，不得用模拟结果宣称上线。
- 依赖通过锁文件复现。结构性数据库更改必须设计迁移。
- 不擅自 commit、push、发布、安装插件代码或对真实 GitHub 仓库执行操作。
