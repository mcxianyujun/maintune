# SMTP

SMTP 是可选服务，可配置 host、port、账号、密码、发件人与 Owner 邮箱。支持 STARTTLS/SSL 由当前设置决定。首次向导允许跳过，生产启用前应在实际邮件环境单独验收。

SMTP 密码加密保存，界面只显示掩码。不要把邮件正文用于承载 Secret 或完整 traceback。
