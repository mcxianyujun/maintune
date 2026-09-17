# GitHub App

Webhook URL：`https://你的域名/webhooks/github`。

Repository permissions：Metadata 只读；Contents、Issues、Pull requests 读写；Checks 与 Commit statuses 只读。订阅 `Issues`、`Issue comment` 和 `Pull request` 事件。

在向导中填写 App ID、可选默认 Installation ID、Private key PEM 和 Webhook Secret。GitHub.com 保持 `https://api.github.com`；GitHub Enterprise Server 可使用自己的 API URL。私钥和 Webhook Secret 加密保存。
