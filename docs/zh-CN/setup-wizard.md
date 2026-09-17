# Setup Wizard 首次运行向导

首次登录后会自动打开九步向导。每一步单独保存，可暂停并稍后从系统设置重新进入。

1. **欢迎**：说明必填能力和可选通知。
2. **系统**：确认本地构建、数据持久化和安全边界。
3. **Model Provider**：填写 OpenAI-compatible Base URL、API Key、Model ID，并选择主 Agent 默认模型。
4. **GitHub App**：填写 App ID、Private Key、Webhook Secret 和可选 Installation ID。
5. **Sandbox**：选择 Local 或 Shipyard Neo 并执行真实读写检查。
6. **Repository**：添加 `owner/repository`、默认分支、测试命令和自动化 Policy。
7. **Optional Services**：SMTP 和通知可跳过，不影响最小闭环。
8. **Diagnostics**：检查 Database、Model、GitHub、Sandbox、Runtime 和 Repository。
9. **Ready**：只有必要诊断完成后才把实例标记为可用。

## 必填与可选

开始真实维护前必须有可用模型、GitHub App、Sandbox、Runtime 和至少一个仓库。SMTP 是可选项。未完成项目会在 Dashboard 的准备进度中显示，并给出下一步入口。

## 常见失败

- Model 失败：检查 Base URL 是否已经包含正确的 API 路径、Model ID 是否存在、API Key 是否有调用权限。
- GitHub 失败：检查 App installation、Private Key PEM 格式、Webhook Secret 和服务器时间。
- Sandbox 失败：确认 Docker/Shipyard 可用、工作目录可写、网络策略允许所需连接。
- Runtime 失败：先运行部署 doctor 与 `pip check`，再查看服务端完整 traceback；Secret 不应出现在前端错误中。
- Repository 失败：确认 GitHub App 已安装到该仓库，并核对默认分支与测试命令。

不要用单个 HTTP 200 代替完成判断；应看到诊断完成、Dashboard 可见，并确认浏览器没有脚本或资源加载错误。
