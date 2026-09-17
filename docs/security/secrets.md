# Secret 管理

管理员令牌和 Fernet 加密密钥位于安装目录私有 `.env`。Provider API Key、GitHub 私钥、Webhook Secret、Sandbox Key 和 SMTP 密码加密入库，API 只返回掩码和存在状态。

不要提交 `.env`、数据库、日志、备份、私钥或测试凭据。备份同时包含加密数据和解密所需密钥，必须整体视为 Secret。轮换管理员令牌后重新登录；轮换加密密钥需要受控的数据重加密流程，不能只替换环境变量。
