# 故障排查

- **页面空白**：确认 HTML 引用的哈希 JS/CSS 均为 200 且 MIME 正确，检查 Console/Network，并用全新浏览器上下文验证可见登录控件。
- **安装构建失败**：检查 Docker daemon、Compose v2、磁盘、DNS，以及 GitHub/PyPI/基础镜像网络。使用标准代理变量后重试。
- **向导模型失败**：确认 Base URL 包含正确 API 前缀，`GET /models` 返回所选 ID。
- **GitHub 失败**：核对 App ID、私钥、Installation、权限、事件订阅和 Webhook Secret。
- **Sandbox 失败**：Local 检查数据目录写权限；Shipyard 检查 Base URL、Key、profile 与 300 秒请求上限。
- **任务失败**：先读 Task timeline 的 failure stage/type/message/attempt，再查服务端完整 traceback。不要在空 Diff 或缺失 CI 上下文下继续 Review。

运行平台对应 `doctor` 脚本可获得安装层诊断。
