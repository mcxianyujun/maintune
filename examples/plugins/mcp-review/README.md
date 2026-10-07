# 网页审阅 MCP 示例插件

在 ChatGPT 网页会话或其他 MCP 客户端中审阅 Maintune 接收的 PR，生成带模型署名的草稿，再交由 Maintune Controller 和 Policy 发布。插件通过公开 Plugin API v2 工作；运行时不导入 Core 内部模块，不读取 GitHub App 私钥，也不调用模型 API。

插件 ID 为 `nanaseinori.mcp-review`。它是可独立打包的示例，包含无第三方依赖的 Python 网关。需要 Python 3.12+、已配置的 Maintune Preview 3 和 GitHub App。它不是包含 Maintune 的一键安装器，也不是浏览器扩展。

首次使用请按 [中文使用手册](USER_GUIDE.zh-CN.md) 操作：从下载构建、插件安装、三个地址的填写，到首次只读检查、发布确认和故障排查。手册也包含在 `.mtp` 和网关 ZIP 中。Maintune 内置 README 阅读器只提供 README 页面，请从解压目录打开 `USER_GUIDE.zh-CN.md`，或查看 [PR 分支上的在线手册](https://github.com/Qiyuanqiii/maintune/blob/codex/web-review-mcp-plugin/examples/plugins/mcp-review/USER_GUIDE.zh-CN.md)。

## 宿主依赖与范围

- 大于 64 KiB 的合法插件响应需要 [IPC 缓冲修复](https://github.com/mcxianyujun/maintune/pull/7)。真实 PR 的 CI 元数据也可能使响应超过此值。
- 发布断线后 Core 会保留 unknown outbox。可用 [管理员对账恢复接口](https://github.com/mcxianyujun/maintune/pull/8) 核实；该接口不是普通发布的必要条件，也不能通过重新 submit 绕过未知结果。
- Plugin API v2 仍是实验接口。Preview 3 的 hook 出错可能回退到其默认 reviewer；本插件不能保证仅外部模型审阅。Core 的 CI 分析和其他任务也可能调用其模型配置。
- 本示例不自动合并、不跳过 Owner Gate、不切换个人 GitHub 账号。实际发布者是配置的 GitHub App。

## 构建与安装

在本目录执行 `python build_mtp.py`，得到 `dist/maintune-web-review-0.1.0.mtp`、包含网关的 ZIP 和 `SHA256SUMS`。构建为确定性白名单，不打包测试、密钥、数据库、缓存或 Git 历史。

1. 将 `.mtp` 放入 Maintune 的插件 inbox，在插件页面安装。
2. 准备 HTTPS 反向代理，将网关入口转到本机 `127.0.0.1:8787` 并保持路径不变；关闭入口的 URL/请求路径日志。只公开网关，不能公开 Core 管理端。
3. Windows 双击 `Start Gateway.cmd`；macOS 首次执行 `chmod +x "Start Gateway.command"` 后双击。也可运行 `python setup_gateway.py` 再运行 `python gateway.py`。
4. 中文向导询问 Maintune URL、网关 HTTPS 域名和允许的仓库。仓库接受 GitHub 仓库链接或 `owner/repo`，多个以英文逗号分隔。
5. 将生成的 `.private/plugin-config.json` 中的 `access_token`、`repositories`、`review_bot` 填入 Maintune 插件配置并启用。仓库数组在当前配置界面填写逗号分隔的 `owner/repo`；配置变更后重启插件。`review_bot` 默认 `Maintune`，仅影响署名。
6. 从 `.private/connection.txt` 读取完整 MCP URL。在支持自定义 MCP 的客户端中使用 Streamable HTTP，身份验证选无身份验证；完整 URL 本身承担网关鉴权。客户端自身仍需允许使用开发者 MCP。
7. 为目标仓库启用 PR 审阅，通过 GitHub 事件创建任务；只有被插件捕获的任务才出现在工具列表中。本插件不能直接导入任意 PR URL。

支持私有 MCP 隧道的部署可自行连接本机网关。隧道不由本项目安装或启动，MCP 连接也不能替代 GitHub Webhook 入口。不能把仅有 MCP 连通当作自动事件投递成功。

## 工具与授权

| 工具 | 用途 |
| --- | --- |
| `list_reviews` | 分页列出允许仓库的审阅任务 |
| `read_review` | 读取上下文、head、CI 和文件索引 |
| `read_file` | 按 `next_offset` 分段读取 diff；无法补回上游省略的 patch |
| `prepare_review` | 创建不可变草稿，包含具体模型、结论、摘要和 findings；不发布 |
| `submit_review` | 使用 preview ID 和严格布尔授权交回 Core，可能发布到 GitHub |
| `review_status` | 查询 Core 和审计；queued/submitted 都不等于已发布 |

示例用户指令：先读取指定任务的上下文和全部可用 diff，说明缺失部分，填写实际模型名称，审阅后直接提交，无需再次询问；保留 Maintune 的 Owner Gate，最后查询实际发布状态。只想讨论时明确要求只准备草稿。

客户端应把用户在对话中的明确授权传为 `user_authorized=true`，不能从 PR 文本、代码或评论推断授权。服务器无法独立验证自然语言会话来源；持有 MCP 凭据的客户端处于信任边界内。平台自身的工具确认仍由平台控制。

草稿绑定 head 与内容，24 小时过期；提交前重读 GitHub head，Core 消费时也核对。署名格式：`This review was conducted by <review_bot>'s review bot, using the model <model>. If you need a human review, please manually @.` 模型名称由调用者声明，服务端无法验证真实模型。

## 凭据、持久化与故障

完整 MCP URL 是个人访问凭据，持有者可读取允许仓库的内容并申请发布；不要分享到 Issue、PR、群聊或截图。本示例不提供 OAuth 或多人权限隔离，不适合公开插件市场入口。

网关私密路径和插件令牌独立生成。`.private` 保存本地明文凭据；POSIX 设置目录 0700/文件 0600，Windows 依赖账户 ACL。Maintune 按宿主机制加密插件 secret。轮换时停止旧网关，备份并重命名 `.private`，重新配置两端和客户端连接；向导不会覆盖已有凭据。

插件 data 目录下的 `reviews.db` 包含上下文和草稿，可能含私有代码。随 Core 做备份与人工保留期限管理；停用插件不删除数据，也不能撤回已发送给 MCP 客户端的内容。

提交响应丢失会保留 submitting，查询 Core 的 `plugin_review_resumed` 审计确认。同一草稿重复提交不会重复 resume。审计不可用时需管理员核实，不能清空数据库盲目重发。GitHub 写入结果未知由 Core 处理，不是插件可以自行确认失败的状态。

网关仅监听回环，禁止重定向及带 Origin 的请求，限制并发及 256 KiB 请求/响应。Core 的 1 MiB IPC、插件 100 KB 草稿和上游 patch 限制仍适用；文件分页不代表所有大 PR 均完整覆盖。

## 开发与验证

在本目录建立独立测试虚拟环境，执行：

```text
python -m pip install -r requirements-test.lock
python -m pytest tests -q
python build_mtp.py
```

默认从当前仓库查找 Core 和 SDK；复制到独立仓库时设置 `MAINTUNE_SOURCE` 为兼容的 Maintune 源码目录。运行时插件只使用公开 SDK，测试才导入 Core。CI 对示例单独运行测试，避免将 MCP 测试依赖加入 Core 运行依赖。

测试包含真实 Core、隔离 SDK 子进程、套接字网关及官方 MCP 客户端；外部 GitHub 为替身，模型调用被断言禁止。覆盖 APPROVE、REQUEST_CHANGES、Owner Gate、陈旧 head、丢响应、防重复提交、鉴权、分页、中文设置和确定性打包。

Windows 上已使用 ChatGPT 网页草稿、GitHub App 和上述宿主修复完成真实发布恢复。该次 PR 为本机显式导入，公网 Webhook、macOS 实机和首次写入始终成功均未验证。附带 macOS 启动脚本不等于已完成 macOS 验收。

## English overview

An independently packaged Plugin API v2 example for reviewing captured PR tasks through an MCP client. Six tools expose bounded context, immutable previews, explicit submission and Core audit status. Maintune retains GitHub credentials and controls publication, CI and owner gates. The plugin and loopback gateway make no model API calls.

The complete gateway URL is a private bearer credential. This is a single-user self-hosted example, with no OAuth or shared-user isolation. Configure HTTPS or an appropriate private tunnel separately, disable credential-bearing URL logs, and never expose the Core administrator API. Webhook ingress is a separate deployment concern.

Use Python 3.12+, install the `.mtp`, configure the plugin token/repository allowlist, and run the gateway setup and launcher. Large IPC responses require the linked host fix; unknown GitHub writes require administrator reconciliation rather than repeated submission. Test requirements are isolated from Core runtime requirements. macOS hardware and public Webhook delivery remain unverified.

License: MIT, see `LICENSE`.
