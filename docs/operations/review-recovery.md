# 恢复写入结果未知的 PR Review

GitHub Review 请求发出后，断线不代表写入失败。Core 保留 `unknown` outbox，普通 retry/recheck 继续返回 409。不要清空记录、重建任务或重新生成草稿来绕过这个状态。

本接口只处理失败或中断的 PR 任务，且任务只能有一个未知 `pr_review`，不能同时有正在执行或对账的外部动作。它不是自动网络重试，也不处理 Issue 评论或合并操作。

## 管理员操作

两个接口沿用 `/api` 的管理员 Bearer 鉴权，不向插件公开管理员凭据。

1. 调用 `GET /api/tasks/{task_id}/review-recovery`。接口读取当前 PR、发布 App、Review 列表和匹配 Review 的行内评论。它返回原 `request`、`outcome`、`review_url`，以及绑定此次检查的 `action_id`、`attempts`、`head_sha`、`payload_sha256`。
2. 阅读原正文、事件与行内评论；检查仓库和 PR。`found` 代表找到唯一完全匹配的已提交 Review；`not_found` 只代表当前完整检查没有找到。
3. 调用 `POST /api/tasks/{task_id}/review-recovery`，原样提供上述四个绑定字段，加上说明原因的 `reason`。`retry_authorized` 必须是 JSON 布尔值。
4. 已找到 Review 时使用 `retry_authorized: false`，Core 关联原 Review 并排队完成后续处理。未找到时，只有管理员明确接受重试风险并传入 `true` 才能排队；距上次写入尝试至少需要两分钟。
5. 查询任务和审计，直到确认实际发布结果。返回 `queued` 本身不是发布成功。

POST 会重新读取 GitHub，不能仅凭旧 GET 结果决策。若预览失效，重新从 GET 开始。查询失败、数量达到检查上限、同一 App 存在待提交 Review、同一 head 的 Review 内容不同、多个匹配、PR 关闭/转为草稿/更新，都会保留阻塞。仓库必须仍启用 PR 审阅，GitHub 安装也必须一致。

## 并发、审计与残余风险

恢复以数据库条件更新领取动作。检查失败或取消会归还 `unknown`；Core 重启也将遗留的 `reconciling` 还原为 `unknown`。写入前保存原请求和尝试时间，防止并发 worker 重复领取。管理员决策记录为 `github_review_reconciled` 或 `github_review_retry_authorized`，包含动作、head、请求摘要和原因。

执行重试前再次查询，可发现旧请求延迟产生的 Review。随后继续经原 Controller、CI 和 Owner Gate；策略改变或重新计算的正文不匹配原请求时仍会停止。

**GitHub API 没有本实现使用的原子幂等键。** 等待两分钟和再次查询不能排除“最后一次查询之后，旧请求才完成”的竞态。查不到不是失败证明，因此需要明确的单次重试授权，不能声称跨网络绝对恰好一次。新的失败仍变成 `unknown`，不会自动反复发布。

旧 Preview 3 只保存 head 和事件。只有审计足以重建无 findings、无附加正文的 APPROVE 时，才支持恢复旧动作；旧行内评论或含 CI 附加文案的请求拒绝推测。新动作直接保存完整请求。无新增表或列，使用既有 JSON 与 Timeline。

## 验证范围

`tests/test_review_recovery.py` 使用真实管理员路由、SQLite 和 Controller，并隔离全部 GitHub 写入。覆盖已成功但响应丢失、明确重试、延迟成功、内容/版本冲突、撤销仓库、过期预览、并发领取、取消、鉴权和旧数据恢复。

Windows 本机曾通过同一份网页草稿完成真实 Review 的恢复，独立读回作者、正文、事件、head 与 URL。该测试从本机导入 PR，不代表公网 Webhook 或其他平台已验收。部署前仍需验证具体数据库与网络环境。
