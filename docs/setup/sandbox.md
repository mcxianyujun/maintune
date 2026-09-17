# Sandbox

Local 适合受信任诊断和兼容场景，只限制路径、cwd、超时、环境变量和输出大小，不是安全隔离边界。处理不可信仓库使用 Shipyard Neo。

Shipyard 配置 Base URL、API Key 和 profile。其单次 shell 请求上限为 300 秒，Controller 仍保留更大的外层工具和任务超时。Setup Wizard 会创建临时工作区并验证读写后销毁。
