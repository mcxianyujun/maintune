# Phase 1 — 外部插件 Agent 验证

日期：2026-09-29。结论：**FAIL；Phase 1 外部开发者验收尚未完成，不得开始 Phase 2。**

## 外部开发者路径

使用公开 `maintune-plugin-sdk`、`maintune-plugin-template` 和公开开发文档，制作独立的 `external.checkpoint` 插件。它只注册 `double(value: int)` Tool；源码没有导入 Maintune Core 私有模块。测试包位于工作区忽略目录 `.tmp/external-checkpoint-20260929/third-party-plugin/`，不属于发行源码。

| 步骤 | 证据 | 结果 |
| --- | --- | --- |
| 全新 Python 3.12 环境安装公开 SDK | SDK 2.0.0 可导入，独立 SDK 测试 3/3 | PASS |
| 基于公开模板创建插件 | 离线测试 2/2；输入 21 返回 42 | PASS |
| 构建 `.mtp` | 明确的五文件白名单；SHA-256 `06766a5d560ff02d9b62645fafd328a57670052b4a760bb9159d61953fb06af8` | PASS |
| Maintune 安装与启用 | 隔离实例扫描有效、安装成功、`runtime_status=running`，注册 `external.checkpoint/double` | PASS |
| 授权 `code_worker` | 推荐 Tool 显式启用后配置返回 `code_worker: [external.checkpoint/double]` | PASS |
| 已安装包的 SDK 隔离运行器 | JSON-RPC `extension.invoke` 输入 21，返回 `{value: 42, plugin_id: external.checkpoint}` | PASS，仅证明插件进程 |
| 真实 OpenHands Agent 调用 | 实际 Agent 调用了该 Tool 一次，Tool 返回 `PluginSchemaError: tool failed`，没有得到数值 | **FAIL** |

## 真实 Agent 任务的环境与结果

验收在一次性、600 MiB 限额的容器内进行。它使用既有 OpenHands SDK 1.47.0 运行依赖和当前 Plugin API v2 候选源码；生产数据库以**只读**方式挂载，仅在进程内读取当前模型配置。插件数据库、安装目录和工作区都位于临时目录。没有修改生产部署、配置或数据库，没有执行 GitHub 写入；测试结束后一次性容器已退出。模型凭据未输出或复制到测试包。

真实模型驱动的 `OpenHandsRuntime.run` 先读取 `TASK.txt`，随后调用 `plugin:external.checkpoint/double`，参数中确有 `value=21`。任务使用 5854 tokens、2 个工具步骤，插件调用次数为 1。最终 Agent 明确报告插件错误，未自行计算答案。

根因：`backend/maintainer/runtime.py` 的插件工具执行路径将 `action.model_dump()` 原样传给 `plugin_manager.invoke_tool`。OpenHands Action 的转储同时包含内部 `kind` 字段，而公开 SDK 为 `double(value: int)` 生成的输入 schema 只有 `value` 且 `additionalProperties=false`。因此 `backend/maintainer/plugin_api_v2.py` 的参数校验拒绝 `kind`，处理器返回 `PluginSchemaError`。这属于 Core/Agent 适配缺陷，不能要求第三方插件接受未公开的内部字段来规避。

本轮按要求**没有修改 Plugin API v2 或 Core 代码**。要完成验收，需要另行修复适配层，仅传递插件声明的模型参数，并增加真实 OpenHands Agent 回归测试；再用同一外部 `.mtp` 重验调用结果为 42，并确认任务记录包含结果。当前测试使用真实模型和运行时，但不是完整 GitHub Issue → TaskProcessor → PR 流程；该边界在下一次验收中应保持清楚。

## 开发者文档摩擦

- 公开 SDK README 原先链接到公开 Maintune main 上尚不存在的 API reference；已在独立 SDK 本地工作区移除失效链接，并更正 Preview 3 不提供 `PluginContext.task_id/agent_id` 的说明。
- 模板 README 原先只覆盖离线测试与打包；已在独立模板本地工作区补充 inbox 安装、启用、给 `code_worker` 授权，以及“离线调用不等于 Agent 调用”的中英文说明。
- 上述 SDK/模板文档修正尚未提交或推送；公开主分支文档仍需同步。Maintune 稳定版文档分支上的 API reference 也尚未进入公开 main。

## Phase 1 剩余阻塞

1. 修复 Core Agent Tool 参数转发缺陷并以真实 Agent 重验；本任务禁止修改 Core，因此保持阻塞。
2. 将已核对的独立 SDK/模板文档修正按正常贡献流程发布，并确保公开 API reference 链接有效。
3. 核对贡献治理的商业再许可边界；详见 `external-contribution-review.md`。

**Phase 2：不得启动。**
