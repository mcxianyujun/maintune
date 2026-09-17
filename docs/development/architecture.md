# 架构

ModelProvider 统一模型调用；AgentRuntime 驱动 Agent loop；SandboxProvider 提供隔离文件和命令；Controller 编排状态机；Policy 决定外部动作；Notification 发送可选通知；Plugin 是实验扩展边界；Audit 保存配置、运行和外部动作证据。

GitHub Webhook 只创建任务。Worker 获取最新 GitHub 上下文，Runtime 生成建议，Controller 验证结果并通过 outbox 执行幂等写操作。失败会记录 stage、exception type、已清理消息和 attempt。

结构和状态机的详细历史说明见上级 [architecture.md](../architecture.md)。
