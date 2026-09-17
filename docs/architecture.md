# 架构与实施计划

## 模块边界

- `api.py`：管理 API、公开 Webhook、轻量持久化任务轮询器。
- `github.py`：GitHub App 认证、读取上下文和 Controller 写操作。
- `tasks.py`：Issue/PR 状态机、独立 Agent 调度、outbox、通知。
- `runtime.py`：结构化模型调用及 OpenHands 1.47.0 adapter。
- `sandboxes.py`：稳定的 Local/Shipyard `SandboxProvider` 接口。
- `db.py`：配置、任务、时间线、Delivery、outbox、review finding 和迁移账本。
- `policy.py`：默认拒绝的确定性 merge 条件；Agent verdict 不能直接触发 merge。

GitHub App、管理员、模型和 SMTP 凭据只存在于 Controller。OpenHands 只获得绑定到单个 workspace 的 shell/read/write 工具，不获得 GitHub 写接口或应用密钥。Issue、PR、评论与仓库内容一律作为不可信数据。

## 状态与幂等

Webhook 先验签，再用 `X-GitHub-Delivery` 持久化去重。任务依次进入 `queued`、`running`，随后进入等待、失败或完成状态。`waiting_for_user` 仅由对应 Issue 的新评论恢复；`waiting_for_owner` 由管理端提交决策恢复并记录 Timeline。

GitHub 写动作先以稳定 action key 写入 outbox。已完成动作复用 external ID/URL；服务在执行中重启或请求结果不确定时标记 `unknown`，禁止盲目重放。运行中的任务重启后标记 `interrupted`，等待状态保持不变。

## 第二阶段实施状态

1. **GitHub 接入与持久化**：已实现 App token、Webhook、仓库策略、任务、时间线、outbox 和 schema v2 添加式迁移。
2. **Issue 工作流**：已实现结构化分析、追问恢复、快照、Sandbox、OpenHands Worker、测试、最多两轮 Reviewer、Controller 建分支/commit/PR。
3. **PR 工作流**：已实现 Draft/Bot 跳过、CI 优先、结构化 review、inline 映射、Request Changes/Comment/Approve 与 finding 去重。
4. **通知与人工决策**：已实现 SMTP、失败不影响主任务、Owner decision UI 和审计。
5. **待真实验收**：创建专用测试仓库，跑通真实 Issue、PR 更新复审、SMTP，并验证真实模型与所选 Sandbox。
6. **后续范围**：安全接通 auto merge、支持新增/删除文件、GitHub 超时动作对账、任务租约恢复与可信插件生命周期。

## 资源与限制

单进程 SQLite 轮询器适合当前小规模自托管实例，不引入 Redis/Celery。Local fallback 不提供强隔离。生产优先使用 Shipyard；仓库快照由 Controller 获取，Sandbox 不持有可 merge 的 token。

## 模型与 Agent 运行配置

Provider 下的每个模型都是独立的 Model Definition，包含可编辑的 capability、reasoning 默认值、生成参数、单次请求超时和扩展参数。旧的字符串模型列表由 schema v3 自动迁移为保守能力定义；迁移不修改 Provider 密钥、Agent prompt、GitHub、Sandbox、仓库或任务历史。

运行时按 `模型默认值 → 主 Agent 覆盖 → 子 Agent 覆盖` 解析配置。模型请求超时按 `子 Agent 覆盖 → 主 Agent 覆盖 → 模型默认 → 300 秒` 选择。工具、任务和 Sandbox 超时也可由子 Agent 单独覆盖。Auto steps 按 Agent 职责选择 soft/hard 预算，并使用确定性的进展与重复动作规则决定扩展或终止；hard limit 始终是上限。

OpenAI-compatible adapter 只发送 capability 明确支持的标准参数。Extra Params 必须是 JSON object，递归拒绝常见密钥字段；`model`、`messages`、reasoning、生成参数和 timeout 等保留字段会被移除，再由 Controller 的标准字段写入，因此标准字段优先。任务首次开始时会保存不含密钥、Base URL、prompt 和 Extra Params 的审计视图，同时保存完整但不含密钥的运行快照；同一任务的重试继续使用该快照。

schema v4 增加普通配置审计表。Model Definition、Main Agent 和 Sub Agent 的恢复默认由后端集中处理：模型恢复 provider 默认语义，Main 保留模型与 prompt 并回到 Auto/unset，Sub Agent 保留身份与 prompt 并回到 Follow Main/Inherit。每次重置返回重新解析的 effective config，并写入仅含对象类型、对象 ID 和 scope 的 `config_reset` 事件。

Runtime 分别执行 model request、tool call 和 whole task deadline。Auto step controller 在执行动作前检查循环和 hard limit；到达 soft limit 后只有检测到进展才扩展预算。任务时间线保留 soft/hard/loop/timeout 事件与实际使用步数，启动时的 resolved snapshot 不会随之后的配置修改而变化。

参考：[OpenHands custom tools](https://docs.openhands.dev/sdk/guides/custom-tools)、[OpenHands Conversation](https://docs.openhands.dev/sdk/api-reference/openhands.sdk.conversation)、[GitHub App authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app)、[Webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)、[Shipyard Bay API v1](https://github.com/AstrBotDevs/shipyard-neo/blob/main/doc/bay_api_v1.md)。
