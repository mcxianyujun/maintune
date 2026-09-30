# PR #8 可靠性缺陷修复记录

日期：2026-09-29
PR：[mcxianyujun/maintune#8](https://github.com/mcxianyujun/maintune/pull/8)
修复基线：`fb2788e3abcfc6d60c5c7dcc26890808c76b1259`
修复分支：`codex/pr8-reliability-fix`，用于更新 PR #8；本报告不代表已合并。

## 根因

1. Review 对账找到已发布写入后，原实现将 Task 重新排队。`process_pull` 再次运行 Reviewer 并重新生成 Review 请求；`action_key` 包含 Review event，而 `github_action` 未拦截同一 Task/head 已完成但 event 不同的动作。因此成功对账仍可能第二次 POST；同一 event 的不同正文则被内容校验拦住，但任务无法继续。
2. `github_action` 将 Outbox 标为 `executing` 后，仅在 `Exception` 中转为 `unknown`。`asyncio.CancelledError` 不属于该捕获范围；外层 Task 变成 `interrupted`，Outbox 却留在 `executing`。管理员对账只接受 `unknown`，普通 retry 又拒绝未解决的 `executing`，只能等进程重启。

## 状态转换及安全边界

- **已对账成功**：`unknown → reconciling → completed`，Task `failed/interrupted → queued → reviewed` 或 `waiting_for_contributor`。恢复后的任务从已保存的 Review 写入检查点继续，使用原 `pr_review_completed` 记录还原技术结论、finding 和最终状态；不再次调用 Reviewer，也不再次提交 Review。若当前产品策略新增 Owner Gate，则停在 `waiting_for_owner`，保留既有 Review，不绕过 Owner 决策。
- **管理员授权重试**：`unknown → reconciling → pending → executing → completed`。只提交 Outbox 保存的原 `review_request`；原 verdict、head、event、正文、仓库策略、installation 必须一致。写入前仍按 PR #8 既有流程再次查询 GitHub，识别延迟到达的旧 Review。
- **POST 时取消或异常**：`executing → unknown`，记录 `github_action_unknown`，异常/取消继续向上抛出，外层 Task 变成 `interrupted` 或失败。管理员可在线进入现有对账接口；普通 retry 仍返回 409，不会盲目重发。
- 对同一 Task/head，已 `completed` 的 Review 阻止另一 event 的 Review POST。新 head 允许正常再审。多个同 head Review 动作或原 verdict 缺失时保守拒绝自动完成，不根据新模型输出猜测原请求。

管理员鉴权、插件权限边界、原有 CAS 认领和审计事件未放宽；未修改数据库结构，旧记录沿用 PR #8 的保守重建规则。运维文档更新了取消处理及恢复任务不重跑 Reviewer 的行为。

## 验证

| 检查 | 结果 |
| --- | --- |
| PR #8 可靠性测试 `tests/test_review_recovery.py` | 36 passed；覆盖真实 `TaskProcessor.process` 恢复路径 |
| 后端全量 `pytest -q` | 183 passed，1 个 Starlette/AnyIO 依赖弃用警告 |
| `git diff --check` | PASS，无空白错误；Windows Git 提示下次写入时将 LF 转换为 CRLF |

新增回归覆盖：已发布 Review 对账后的真实 Task 完成且 POST 数为 0；同 Task/head 的不同 event 被拦截；授权重试只使用原请求且再次运行不会重复发送；真实 Task 在 Review POST 等待期间取消，Outbox 立即 `unknown`，普通 retry 被阻止，在线对账后完成；`REQUEST_CHANGES` 恢复 finding 与等待贡献者状态；产品策略变化时仍触发 Owner Gate；新 head 的再审不受旧 `completed` 动作阻塞。

## 剩余限制与交付状态

- GitHub API 没有此流程可用的原子幂等键。管理员检查显示“未找到”后，旧请求仍可能非常晚才完成；原有至少两分钟等待、显式管理员授权及写入前二次对账继续保留，不能宣称网络层 exactly-once。
- 进程被强制杀死且未重启时，无法在同一进程中继续操作；正常服务启动会把残留 `executing/reconciling` 归一化为 `unknown`。不采用自动按时间把正在执行的 POST 转为可重试，因为这可能与尚未完成的 GitHub 写入竞态。
- 只做了本地隔离 GitHub 模拟写入测试；没有对真实 GitHub PR 再发 Review。PR 分支落后当前 `main`，维护者审查时还需以最新 `main` 执行远端 CI。**不合并 PR #8，等待维护者审查。**
