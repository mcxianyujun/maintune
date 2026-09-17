# Reasoning

Reasoning mode、effort 和 budget 只有在模型能力声明支持时才会下发。`inherit` 表示沿用上一层，`unset` 表示不发送预算。Provider adapter 会过滤 `model`、`messages`、timeout 和生成参数等保留字段，避免 extra params 覆盖 Controller 决策。
