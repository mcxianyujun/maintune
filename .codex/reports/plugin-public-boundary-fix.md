# Plugin API v2 公开 Tool 请求边界修复

日期：2026-09-29。范围：Phase 1 外部开发者 Agent Tool 验证。未启动 AnySearch Phase 2，未提交、推送、部署或发布。

## 根因与修复

`OpenHandsRuntime` 将 OpenHands `Action.model_dump()` 整体交给 `PluginManager.invoke_tool`。该内部对象除插件公开参数外还带 `kind`；公开 SDK 为 `external.checkpoint/double(value: int)` 生成的严格输入 schema 只接受 `value`，所以真实 Agent 调用在进入插件前被拒绝。

现在创建 Tool 时从注册的 `input_schema.properties` 固定公开字段集合；执行时仅序列化这个集合内实际提供的字段，再送到 `PluginManager`。`kind`、任务标识和运行时元数据不会作为插件 Tool 参数转发。未提供的可选字段保持缺省，交由插件处理器使用其声明的默认值。SDK 的未知字段拒绝规则、capability、权限和 Plugin API v2 结构均未放宽或扩展。

修改：`backend/maintainer/runtime.py`、`tests/test_plugin_api_v2_core.py`、`docs/plugin-api-reference.md`。回归测试证明 Core 内部字段被剔除、公开 `query` 可正常调用、未经剔除的 `kind` 仍被严格校验拒绝。

## 复验

| 检查 | 结果 |
| --- | --- |
| 公开 SDK / 模板制作的 `external.checkpoint` 插件重新构建 | PASS；`.mtp` SHA-256 `06766a5d560ff02d9b62645fafd328a57670052b4a760bb9159d61953fb06af8`，与原独立构建一致 |
| 隔离 Maintune 安装、启用、给 `code_worker` 授权 | PASS；注册 `external.checkpoint/double` |
| 真实 OpenHands `code_worker` Agent 任务 | PASS；先读 `TASK.txt`，再选中并调用插件 Tool 一次，输入 `value=21`，插件返回 `{"value":42,"plugin_id":"external.checkpoint"}`，Agent 完成并报告 42；5178 tokens、2 步 |
| Plugin API v2 核心测试 | PASS；31 passed |
| 完整后端测试 | PASS；147 passed、1 个既有依赖弃用警告 |
| 中英文文档一致性 | PASS；9 对文档 |
| `git diff --check` | PASS |
| 生产服务与测试环境清理 | PASS；一次性容器退出、临时服务器文件清理，生产容器健康、`/healthz` 返回 ok |

真实验收在资源限额为 600 MiB 的一次性容器中运行，生产数据库只读挂载，仅用于读取当前模型配置。插件数据库、安装路径和 Sandbox 工作区均为一次性目录。无 GitHub 写入，未修改生产配置或密钥。本验收验证真实模型和 OpenHands Tool 调用；它不是完整 GitHub Issue → PR 流程。

## Phase 1 状态

**Agent Tool 外部开发者验证已通过，原阻塞已解除。Phase 1 整体仍未完成公开交付。** 独立 SDK 与模板 README 的已核对修正仍是各自本地未提交修改；本分支上的公开 API reference 修正也尚未发布。因此公共仓库文档目前仍可能出现失效链接或缺少真实 Agent 授权步骤。项目规则禁止未经明确授权自行提交或推送，故本轮保留可审阅补丁，不把本地通过冒充公开开发者流程已完成。贡献治理边界见 `external-contribution-review.md`；AGPL-only 普通修复与商业再许可应分开处理。

**Phase 2 AnySearch：未启动。**
