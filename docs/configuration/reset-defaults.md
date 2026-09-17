# 恢复默认

可以按 Reasoning、Generation、Steps、Timeouts 分组恢复，也可 Reset all。Reset 只清除对应覆盖，使值回到 Auto、Inherit 或系统默认。

Reset 不删除 Provider、API Key、模型、Agent、Prompt、GitHub、仓库或历史。操作由后端执行并写入不含 Secret 的 `config_reset` 审计；重复 Reset 是幂等的。
