# Maintune 外部贡献评审记录

日期：2026-09-29。范围：PR #7、#8、#9；本轮仅 #7 获授权并完成合并。

## 现行贡献规则

- [CONTRIBUTING.md](../../CONTRIBUTING.md) 已存在。提交贡献即确认有权按 AGPL-3.0-only 提供；普通修复可以仅进入 AGPL 发行版。
- [CLA 草案](../../CONTRIBUTOR-LICENSE-AGREEMENT.md) 和 [贡献授权方案](../../docs/licensing/contributor-licensing.md) 已存在。**需要用于双授权核心或 Commercial License 的贡献**必须另行签署最终协议；收到 PR 不自动取得商业再许可权。当前草案仍要求法律审阅，不等于已签署协议。
- 未发现 DCO 或 Signed-off-by 要求、`CODE_OF_CONDUCT.md`、自动 CLA/DCO 检查工作流。CI 与 release-candidate workflow 不承担贡献者授权检查。
- 因此不存在“所有 PR 必须先签 CLA”的规则；也不能把 AGPL 入站贡献自动纳入商业授权。稳定版前建议将 CONTRIBUTING 中的 AGPL-only 与双授权贡献分类、人工记录流程写得更可操作，并考虑补充 Code of Conduct；不因后者缺失阻挡普通小修复。

## PR #7 — 隔离插件读取缓冲

[PR #7](https://github.com/mcxianyujun/maintune/pull/7) head `51265e0a9010fffb2355db2f51030a5e4b85a3cc`。

**决定：批准并合并，作为 AGPL-only 普通修复。** 原实现使用 `asyncio` 默认约 64 KiB 的 subprocess stdout reader，而 Plugin API v2 已允许最大 1 MiB 的单条消息。补丁只把现有 `MAX_MESSAGE_BYTES` 交给 `create_subprocess_exec(limit=...)`；发送和接收侧原有 1 MiB 检查保持不变，未增加 capability 或改变协议语义。回归覆盖 80 KiB 和接近 1 MiB 的响应，以及后续请求仍可运行。

贡献者 PR 描述未声称签署商业 CLA；按现行政策仅接受进入 AGPL 发行版，评审未授予商业再许可权。[PR CI run 36542536123](https://github.com/mcxianyujun/maintune/actions/runs/36542536123) 的 `test` 和 `windows-scripts` 均成功。维护者批准 review `5350415742`，使用普通 merge commit 合并，SHA：`81a00dad17a657ec28e357aae109c418e9fa41bc`。[合并后 CI run 36549287669](https://github.com/mcxianyujun/maintune/actions/runs/36549287669) 同样成功，`test` 与 `windows-scripts` 均通过。

## PR #8 — GitHub Review 未知写入恢复

[PR #8](https://github.com/mcxianyujun/maintune/pull/8) head `fb2788e3abcfc6d60c5c7dcc26890808c76b1259`，仍为 Draft；**未合并**。该方案有实际可靠性价值：它为 `unknown` Review outbox 增加只限管理员的检查与恢复，校验原请求、PR head、App 身份与已发布 Review，避免断线后直接盲重试。当前 PR CI 成功。

但它改变 Controller 的外部写入状态流：`unknown → reconciling → completed/pending`，并新增管理员重试授权。GitHub 无原子幂等键，最后一次检查与重发之间仍可能出现延迟写入；PR 文档已坦承此风险。建议**不把它作为 Phase 1 或开始 Phase 2 的前置条件**；若要纳入 v0.1.0，作为独立的稳定版可靠性审查，要求基于已更新 main 重新跑 CI、复核真实断线/并发/重启路径、审计完整 Review 请求在数据库与备份中的敏感性，并由 Owner 明确接受残余重复 Review 风险。若计划将这部分 Core 代码用于商业再许可，应先按现行政策处理贡献者 CLA；目前不能推定已取得该授权。

## PR #9 — MCP 网页审阅示例

[PR #9](https://github.com/mcxianyujun/maintune/pull/9) head `84660fb603b7dcbddb3ee2f55d82b692e9c39bc9`，仍为 Draft；**未合并**。归属路线图 **Phase 3 — MCP Review Example**，不属于当前 Phase 1/2。当前 PR CI 与独立 MCP example workflow 成功，不改变本轮延期决定。

未来合并前建议请求改进或确认：完整网关 URL 是 bearer 凭据，反向代理与访问日志不得泄漏路径；`user_authorized=true` 由持有凭据的客户端声明，服务器不能独立证明自然语言授权，必须保持单用户信任边界且不能宣称更强鉴权；私有代码与草稿 SQLite 的保留/备份边界需明确；README 中指向贡献者分支的使用手册链接应改成合并后稳定路径；在合并了 #7 的 main 上重跑集成测试。不要因示例测试通过就宣称公网 Webhook 或 macOS 实机验收完成。

## 阶段结论

贡献规则已核对，#7 已批准、合并且 post-merge CI 通过。#8 与 #9 保持开放 Draft，本轮没有修改或合并。Phase 1 真实 Agent Tool 调用仍失败，见 `phase-1-agent-validation.md`；**Phase 2 暂不能开始。**
