# 模型 Provider

配置 OpenAI-compatible Base URL、API Key 和实际 Model ID。诊断会调用 `GET /models` 并确认模型存在。模型能力声明控制 reasoning、temperature、top_p 和输出限制是否允许下发。

API Key 保存后不会完整回显。先用诊断请求验证返回、Token usage、超时和 resolved config，再启用真实仓库自动化。
