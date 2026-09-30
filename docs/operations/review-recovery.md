# 恢复写入结果未知的 PR Review

GitHub Review 请求发出后，断线不代表写入失败。Core 保留 `unknown` outbox，普通 retry/recheck 继续返回 409。不要清空记录、重建任务或重新生成草稿来绕过这个状态。

本接口只处理失败或中断的 PR 任务，且任务只能有一个未知 `pr_review`，不能同时有正在执行或对账的外部动作。它不是自动网络重试，也不处理 Issue 评论或合并操作。

## 管理员操作

两个接口沿用 `/api` 的管理员 Bearer 鉴权，不向插件公开管理员凭据。

1. 调用 `GET /api/tasks/{task_id}/review-recovery`。接口读取当前 PR、发布 App、Review 列表和匹配 Review 的行内评论。它返回原 `request`、`outcome`、`review_url`，以及绑定此次检查的 `action_id`、`attempts`、`head_sha`、`payload_sha256`。
2. 阅读原正文、事件与行内评论；检查仓库和 PR。`found` 代表找到唯一完全匹配的已提交 Review；`not_found` 只代表当前完整检查没有找到。
3. 调用 `POST /api/tasks/{task_id}/review-recovery`，原样提供上述四个绑定字段，加上说明原因的 `reason`。`retry_authorized` 必须是 JSON 布尔值。
4. 已找到 Review 时使用 `retry_authorized: false`，Core 关联原 Review 并排队完成后续处理，不再生成新的 Review。未找到时，只有管理员明确接受重试风险并传入 `true` 才能排队；距上次写入尝试至少需要两分钟。该次执行只使用 Outbox 保存的原请求，不重新让 Reviewer 生成另一份正文或事件。
5. 查询任务和审计，直到确认实际发布结果。返回 `queued` 本身不是发布成功。

POST 会重新读取 GitHub，不能仅凭旧 GET 结果决策。若预览失效，重新从 GET 开始。查询失败、数量达到检查上限、同一 App 存在待提交 Review、同一 head 的 Review 内容不同、多个匹配、PR 关闭/转为草稿/更新，都会保留阻塞。仓库必须仍启用 PR 审阅，GitHub 安装也必须一致。

## 并发、审计与残余风险

恢复以数据库条件更新领取动作。检查失败或取消会归还 `unknown`；Review POST 期间任务取消也会立即把 `executing` 标记为 `unknown`，允许在线对账，但普通任务 retry 仍被阻止。Core 重启会将遗留的 `executing/reconciling` 还原为 `unknown`。写入前保存原请求和尝试时间，防止并发 worker 重复领取。管理员决策记录为 `github_review_reconciled` 或 `github_review_retry_authorized`，包含动作、head、请求摘要和原因。

执行重试前再次查询，可发现旧请求延迟产生的 Review。恢复任务会重新读取当前 PR 与仓库策略，核对原 verdict 和原请求，再从 Review 写入检查点完成 Task；不重跑 Reviewer。PR head 或仓库权限变化会阻止旧请求继续执行；新 head 仍可走正常的独立再审流程。

新 Review 写入在请求发出前，将仓库、PR 编号、head SHA、Review 事件、完整请求及其 SHA-256 摘要保存到 Task/Outbox。新 Outbox 的唯一键按仓库、PR 编号和 head SHA 建立。同一 head 的后续 Webhook Task 会检查所有既有 Review 动作：相同请求且已完成时复用原结果；未知、执行中、等待管理员对账或内容不同的动作会阻止新写入，并在新 Task 时间线记录原动作 ID。未知动作仍须通过原 Task 的管理员恢复接口处理，不会由新 Task 自动重试或绕过授权。旧版带事件后缀的动作键继续可读取和恢复。

复用已完成 Review 的新 Task 仍会完成自身状态更新，并记录 `pr_review_reused` 和 `review_completion_side_effects_skipped` 时间线。该次复用不再次发送 `pr.reviewed` / `pr.changes_requested` 插件完成事件，不再次调用 `task.finally`，也不重复发送任务完成邮件；原 Task 的生命周期回调保持不变。此限制只针对相同 head、相同请求、同一次 Task attempt 的 Review 复用；新 head 的独立审阅照常触发回调。

**GitHub API 没有本实现使用的原子幂等键。** 等待两分钟和再次查询不能排除“最后一次查询之后，旧请求才完成”的竞态。查不到不是失败证明，因此需要明确的单次重试授权，不能声称跨网络绝对恰好一次。新的失败仍变成 `unknown`，不会自动反复发布。

旧 Preview 3 只保存 head 和事件。只有审计足以重建无 findings、无附加正文的 APPROVE 时，才支持恢复旧动作；旧行内评论或含 CI 附加文案的请求拒绝推测。旧动作若保存了原请求但 Task 缺少 head，可按 Outbox 中不可变的 head、事件和请求进行保守对账，并再次核对 GitHub 当前 head；新动作缺少 Task head 则拒绝恢复。无新增表或列，使用既有 JSON 与 Timeline。

## 验证范围

`tests/test_review_recovery.py` 使用真实管理员路由、SQLite 和 Controller，并隔离全部 GitHub 写入。覆盖已成功但响应丢失、明确重试、延迟成功、内容/版本冲突、撤销仓库、过期预览、并发领取、取消、鉴权和旧数据恢复。

Windows 本机曾通过同一份网页草稿完成真实 Review 的恢复，独立读回作者、正文、事件、head 与 URL。该测试从本机导入 PR，不代表公网 Webhook 或其他平台已验收。部署前仍需验证具体数据库与网络环境。
