# 安全模型

信任边界包括浏览器管理员、Controller、数据库/Vault、模型 Provider、GitHub、Agent Runtime 与 Sandbox。外部 Issue、PR、代码和模型输出一律视为不可信输入。

Sandbox 不接收 GitHub App 私钥、Webhook Secret、管理员令牌或 Provider 管理权限。Agent 只能通过受控工具提出读写和命令请求；Controller 校验仓库、路径、大小、状态与 Policy 后才执行外部写操作。模型不得自行 merge。

Local executor 不是强隔离。公网管理端必须使用 TLS，并限制主机和备份访问。服务重启不会静默重放正在执行的外部动作。
