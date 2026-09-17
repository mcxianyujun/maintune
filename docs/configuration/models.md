# 模型配置

Provider 保存连接信息，Model Definition 保存能力与默认参数，Main Agent 和 Sub Agent 只保存引用和允许的覆盖。运行时按 Model defaults → Main settings → Agent override 的顺序解析，并把不含 Secret 和 Prompt 的快照写入审计。

删除或禁用正在被引用的模型会被拒绝。连接诊断和真实 Agent 运行均使用解析后的 Base URL、Model ID、超时与参数。
