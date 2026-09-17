# Runtime budget

Auto steps 根据角色选择软上限和硬上限；在有进展时按 extension 延长，但永不超过硬上限。循环检测会在重复工具行为达到阈值时停止。模型请求、工具调用、整个任务与 Sandbox TTL 使用独立超时。

超时或预算耗尽会进入明确失败阶段，并在任务时间线保存已清理的异常类型、消息和 attempt；服务端日志保留 traceback。
