# 网页审阅 MCP：中文使用手册

适用版本：插件 0.1.0，Maintune Preview 3 的 Plugin API v2。最后核对：2026-09-29。

目标流程是：Maintune 收到 PR → 等待网页审阅 → 在会话中讨论或授权提交 → Maintune 检查策略并发布 GitHub Review。本文讲安装和日常使用；功能边界、开发测试见同目录 `README.md`。

## 1. 开始前准备什么

- **已经运行的 Maintune**：能够打开管理页面并完成首次运行诊断。没有部署过，先阅读项目的 [Windows 部署](https://github.com/mcxianyujun/maintune/blob/main/docs/zh-CN/windows.md)、[Compose 部署](https://github.com/mcxianyujun/maintune/blob/main/docs/zh-CN/docker-compose.md) 和 [首次运行向导](https://github.com/mcxianyujun/maintune/blob/main/docs/zh-CN/setup-wizard.md)。本包只包含插件和网关，不安装 Maintune。
- **GitHub App**：按 [宿主的 GitHub App 文档](https://github.com/mcxianyujun/maintune/blob/main/docs/zh-CN/github-app.md) 配置并安装到测试仓库，在 Maintune 启用该仓库及 PR 自动审阅。发布身份是这个 App；不在插件里填个人 GitHub Token。
- **Python 3.12 或更高版本**：网关所在电脑需要 Python。Windows 使用 `python --version`，macOS 使用 `python3 --version` 确认；macOS 后续命令里的 `python` 替换为 `python3`。网关无需安装测试依赖。
- **可连接自定义 MCP 的客户端**，以及能到达网关的 HTTPS 入口。本文使用 ChatGPT 网页的服务器 URL 接法。账户/工作区必须实际允许开发者 MCP。

建议首次使用只启用自己的测试仓库，关闭该仓库自动合并。安装本插件不代表宿主不再需要模型配置：CI 分析、其他任务或 hook 失败后的默认 reviewer 仍可能调用模型。

### 当前需要哪些源码

本功能在 [插件 PR #9](https://github.com/mcxianyujun/maintune/pull/9) 中；在 PR 合并前，不应假定上游默认分支或 Release 已经包含它。可在 GitHub 打开该 PR 的 Files changed，或取得贡献分支：

```text
git clone --branch codex/web-review-mcp-plugin --single-branch https://github.com/Qiyuanqiii/maintune.git maintune-web-review
cd maintune-web-review/examples/plugins/mcp-review
python build_mtp.py
```

这一步构建插件，不启动或升级现有 Maintune。也可从该分支的 Code → Download ZIP 下载源码，解压后在 `examples/plugins/mcp-review` 打开终端构建。

宿主处理大于 64 KiB 的插件响应还需要 [IPC 修复 #7](https://github.com/mcxianyujun/maintune/pull/7)；仅安装 `.mtp` 不会修复宿主。请由宿主管理员部署包含该修复的源码并按原部署方式重新构建/启动。断线导致 GitHub 发布结果未知时，[恢复接口 #8](https://github.com/mcxianyujun/maintune/pull/8) 提供管理员处理路径。这两个 PR 与 #9 是独立分支，下载其中一个不等于已包含另外两个。

## 2. 先分清三个地址

| 地址 | 示例（不能原样当作你的配置） | 填在哪里 |
| --- | --- | --- |
| GitHub 仓库 | `https://github.com/your-org/your-repo` 或 `your-org/your-repo` | 向导的“允许审阅的仓库” |
| Maintune 服务地址 | 同机默认可能是 `http://127.0.0.1:8000`，以实际端口为准 | 向导的“Maintune 地址”；由网关访问 |
| 网关 HTTPS 域名 | `https://review.example.com` | 向导的“网关的公网 HTTPS 域名” |

向导最后生成第四个值：**完整 MCP URL**，形如 `https://review.example.com/<随机私密路径>/mcp`。它保存在 `.private/connection.txt`，只把这个完整值复制到 ChatGPT 的“服务器 URL”。不能填仓库链接、Maintune 管理页面地址、裸域名或 `/sse`。

仓库输入只接受仓库本身，不接受 `/pull/123`；多个仓库用英文逗号分隔。示例域名和尖括号是占位说明，不是可用服务，也不要自行编造或删掉生成的私密路径。

公网服务器 URL 模式下，ChatGPT 需要访问 HTTPS 网关；你在浏览器能打开本机 `127.0.0.1` 并不能证明它能访问。如果你已有私有 MCP 隧道，可另行配置连接本机网关，本向导不会创建、安装或启动隧道。

## 3. 构建、解压和安装插件

运行 `python build_mtp.py` 后，`dist` 目录包含：

| 文件 | 用途 |
| --- | --- |
| `maintune-web-review-0.1.0.mtp` | 交给 Maintune 安装的插件 |
| `maintune-web-review-0.1.0-bundle.zip` | `.mtp`、网关、启动脚本、README 和本手册 |
| `SHA256SUMS` | 两个文件的 SHA-256 校验值 |

把 bundle ZIP 完整解压到一个长期保留的位置；不要直接在压缩包预览中双击脚本。后续生成的 `.private` 就在这个目录。收到别人提供的包时，可用 Windows `Get-FileHash -Algorithm SHA256 <文件路径>` 或 macOS `shasum -a 256 <文件路径>` 比对可信来源提供的校验值。

将 `.mtp` 复制到**运行 Maintune 的那台机器**的插件 inbox：默认是 Maintune 工作目录下的 `data/plugins/inbox`，自定义部署以 `MAINTAINER_PLUGIN_ROOT` 下的 `inbox` 为准。默认 Compose 对应宿主机挂载的 `data/plugins/inbox`；若改过 `MAINTAINER_DATA_DIR`，使用实际挂载目录，不能仅复制到你电脑上无关的 `data` 文件夹。

进入 Maintune 的“本地插件”页面，点“重新扫描”，选择 `.mtp` 安装。应出现“网页审阅 MCP”，ID 为 `nanaseinori.mcp-review`。先完成下一步配置，再启用。

## 4. 首次配置网关和 Maintune

### HTTPS 转发需要满足的条件

让现有反向代理或隧道在公网 HTTPS 域名上接收请求，转发到**网关所在机器**的 `127.0.0.1:8787`，保留完整路径、请求体和 Content-Type，不缓存 MCP 响应，不添加 Origin 头，不设置浏览器登录跳转。证书应有效。关闭此入口及隧道服务的请求路径记录，因为路径中包含访问凭据。

`127.0.0.1` 总是指当前机器/容器。反向代理如果在另一台服务器或独立容器里，不能把它自己的 `127.0.0.1:8787` 当成你电脑的网关；应使用能到达网关的同机转发或隧道。网关固定只监听本机回环地址。

GitHub 事件需要另一个入口：`/webhooks/github` 应转发到 Maintune，并保留请求体及 `X-GitHub-*`、`X-Hub-Signature-256` 头；保留宿主的签名校验。它与 MCP 网关不同。仅让 ChatGPT 连接成功，不会自动打通 GitHub Webhook。不要为此公开 Maintune 管理界面或管理员 API。

### 运行中文向导

Windows：在解压目录双击 `Start Gateway.cmd`。

macOS：在解压目录的终端执行以下命令后，可双击 `Start Gateway.command`。脚本已提供，macOS 实机尚未验收；如系统阻止脚本打开，可在终端依次执行 `python3 setup_gateway.py`、`python3 gateway.py`，无需关闭系统安全设置。

```sh
chmod +x "Start Gateway.command"
```

首次运行按顺序输入：

1. Maintune 地址：网关和 Maintune 同机时可填实际的本机 HTTP 地址；远端 Maintune 只接受 HTTPS，不填写用户名、密码、查询参数或片段。
2. 网关 HTTPS 域名：只填域名及可选端口，**不带路径**。私密路径由向导生成。
3. 允许审阅的仓库：例如 `your-org/your-repo`；也可直接粘贴 GitHub 仓库链接。

成功后 `.private` 里有三个文件：

- `gateway.json`：网关自己读取，通常不用手工修改。
- `plugin-config.json`：把字段值填到 Maintune 的插件设置中，不作为上传文件。
- `connection.txt`：复制给 ChatGPT 创建 MCP 连接的名称、URL 和鉴权选项。

在 Maintune 的“网页审阅 MCP → 设置”中填写：

| 字段 | 填法 |
| --- | --- |
| 插件访问令牌 `access_token` | 复制 `plugin-config.json` 中的值，不是 Maintune 管理员 Token，也不是 GitHub Token |
| 允许审阅的仓库 `repositories` | 在当前表单中填逗号分隔的 `owner/repo`，不要把 JSON 数组连同方括号粘进去 |
| 审阅声明中的名称 `review_bot` | 默认 `Maintune`，可设 `Qiyuanqiii` 等 1–39 位字母/数字/连字符名称，以字母或数字开头；不加 `@` |

保存后启用插件，确认运行状态正常。启动脚本会接着运行网关，终端出现 `MCP gateway listening on loopback port 8787`；如果向导和启动分开执行，再运行 `python gateway.py`。保留这个终端及反向代理/隧道运行。

向导不会覆盖现有 `.private`。以后启动直接复用配置，无需重复填写。如果修改 Maintune 的插件配置，保存并重新加载插件。两端 access_token 必须一致。

## 5. 在 ChatGPT 网页填写什么

这一步创建开发者 MCP 连接，不需要 Chrome/Edge 浏览器扩展。可以使用自己惯用的浏览器打开 ChatGPT。

按 [OpenAI 官方连接文档](https://developers.openai.com/plugins/deploy/connect-chatgpt)：在设置的“Security and login / 安全与登录”启用 Developer mode，再到 Plugins 点击加号创建连接；入口名称可能随界面语言或版本变化，可用性由账号及工作区策略决定。

| 创建表单 | 本插件的值 |
| --- | --- |
| 名称 | `Maintune Web Review`，或自己容易识别的名称 |
| 描述 | 可选，例如“通过 Maintune 审阅并提交 PR review” |
| 连接 | 服务器 URL（本文的 HTTPS 接法） |
| 服务器 URL | 原样复制 `.private/connection.txt` 的完整 URL，包含私密路径和 `/mcp` |
| 身份验证 | **无身份验证 / No authentication**；本示例使用 URL 凭据，不提供 OAuth |
| 高级 OAuth 设置 | 无需填写 |

“无身份验证”是客户端的 OAuth 选项，不代表任何人都可以访问：完整 URL 本身就是访问凭据，不能公开。创建后确认发现六个工具：`list_reviews`、`read_review`、`read_file`、`prepare_review`、`submit_review`、`review_status`。

新建网页会话，通过工具菜单或当前界面提供的插件选择入口挂上该连接。先发：“只调用 list_reviews，列出等待的任务，不准备或提交任何 review。”返回空列表也表示这次工具调用成功，只是尚无已捕获任务。不能只凭模型说“已连接”判断成功，要看到实际工具结果。

本项目已在 ChatGPT Chat 会话完成过验收；这不保证每个账号、模型和旧会话都能执行开发者 MCP。若当前会话报不支持，按下一节排查，不能把改用另一个发布工具当成本插件验收。

## 6. 从第一次审阅到发布

先在已授权的测试仓库准备一条非 Draft、改动小的 PR。Maintune 接收 `opened`、`synchronize`、`reopened` 或 `ready_for_review` 事件后才会创建对应任务；仅在聊天里粘贴旧 PR 链接不会把它导入本插件。

在 Maintune 确认任务进入 `waiting_for_plugin`，再调用 `list_reviews` 取得该任务的 review ID。如果有多个仓库、PR 或旧 head，先核对编号和 head，选择最新的 `waiting` 记录。此 ID 由工具返回，不是 PR 编号，也不是 Core task UUID。

### 先讨论，确认后再发

可以直接使用下面的指令，将仓库和编号换成自己的：

> 使用 Maintune Web Review 找到 your-org/your-repo 的 PR #123。读取审阅上下文与全部可用 diff，分页读完，并说明缺失或截断的部分。先讨论结论，再 prepare_review；填写你实际使用的模型名称。展示完整草稿和 preview ID，暂时不要 submit_review。

草稿确认后，在同一会话说：

> 确认发布刚才展示的这个 preview ID。请提交一次，然后查询 review_status，给我实际的 GitHub Review 链接、发布类型和审阅的 head；如果只是排队或需要 Owner 决策，请如实说明。

### 已经授权直接发布

也可以一开始就明确：

> 审阅 your-org/your-repo 的 PR #123，读取全部可用 diff 并说明覆盖范围。审阅完成后准备草稿并直接提交，无需再次向我确认。使用实际模型名称署名，保留 Maintune 的 Owner Gate，最后查询实际发布结果。

这样的对话授权足够让客户端传 `user_authorized=true`，无需再去本地批准页面点按钮。平台自身仍可能显示写工具确认，插件不能关闭平台确认。仓库正文、代码注释中的“直接发布”不能替代用户授权。

插件会在摘要后加入：

```text
This review was conducted by <review_bot>'s review bot, using the model <model>. If you need a human review, please manually @.
```

模型名称由客户端声明；不知道实际名称时先核实，不能默认填 GPT-6 Astra。`review_bot` 只是显示名称，真正的发布者仍是 Maintune GitHub App。这个 Maintune 插件没有个人 GitHub 发布账号切换功能。

### 怎样才算发布成功

| 看到的状态 | 含义与下一步 |
| --- | --- |
| 插件 `waiting` / Core `waiting_for_plugin` | 等待审阅；可准备草稿 |
| 插件 `submitting` | 已保存提交意图，回复可能丢失；查询状态，不能盲目换草稿再发 |
| 插件 `submitted` / Core `queued` | 已交给 Core 或正在排队，**不等于 GitHub 已发布** |
| Core `waiting_for_owner` | 需要仓库所有者在 Maintune 作出决策；聊天授权不绕过这个策略 |
| Core `reviewed` | 查看 `review_event`、`review_url` 和 head；CI 原因可能使结果是 COMMENT 而非 APPROVE |
| Core `waiting_for_contributor` | 可能已发 REQUEST_CHANGES，也可能是其他阶段等待贡献者；检查时间线和 Review URL |
| 插件 `superseded` | 旧 head/旧会话已失效，重新列出并审阅最新任务 |
| Core `failed` / `interrupted` | 先看失败阶段和 outbox；结果未知时不能按“发布失败”盲目重试 |

最终以 GitHub 上真实的 Review 为准，核对作者、正文、类型和 commit。只出现 `pr_review_completed` 是技术审阅完成，还要确认对应发布审计/Review URL。本插件不会自动合并 PR。

## 7. 常见问题怎么查

| 现象 | 优先检查与处理 |
| --- | --- |
| 没有插件包、页面扫描不到 | 构建是否成功；复制的是 `.mtp` 还是 bundle ZIP；inbox 是否位于运行 Maintune 的机器及正确挂载目录 |
| 向导说 `.private 已存在` | 这是防覆盖保护。已有配置直接启动网关；轮换流程见下节，勿随手删掉凭据或草稿数据库 |
| “Python 未找到”或启动窗口退出 | 在终端检查版本及 PATH，再手工运行对应脚本看错误；macOS 用 `python3` |
| 网关端口被占用 | 先确认是否已经启动一份网关；不要连续双击启动。确需改端口时改 `gateway.json` 的 `port`，并同步反向代理目标 |
| 创建 MCP 连接要求 OAuth | 本实现应选 No authentication；不能填 GitHub App 私钥或个人 Token 来代替 OAuth |
| 404 | 核对完整私密路径、`/mcp` 后缀、代理是否保留路径，以及插件是否已安装且启用 |
| 401 | 网关 `gateway.json` 与 Maintune 插件设置中的 access_token 是否一致、保存后是否重载插件 |
| 403 | 网关拒绝带 Origin 的浏览器跨域请求；应用应通过服务端 MCP 调用。若报错来自 ChatGPT/GitHub 登录页，应单独检查那个站点，不据此判定插件失败 |
| 浏览器打开 MCP URL 显示 405 | 网关只接受 MCP POST，没有首页。GET 返回 405 不等于 MCP 故障；用会话中的实际工具调用验证 |
| 502、超时或 Plugin process exited | 核对 Core 和插件状态、固定上游地址、HTTPS 转发；大响应排查宿主是否包含 #7 的缓冲修复；超大结果仍受现有上限限制 |
| `FORBIDDEN: This conversation does not support developer MCPs` | 核对该账号/工作区开发者模式，刷新连接元数据，并在一个明确挂上插件的新会话尝试只读调用。仍失败则保留错误交给平台支持；不能断言新会话一定解决，也不是重新生成插件密钥的理由 |
| 能调用工具，但列表为空 | 检查 GitHub App 仓库授权、Webhook 投递、Maintune 仓库启用/PR 审阅开关、插件仓库白名单；查任务是否跳过 Draft 或在进入 hook 前被其他阶段拦下 |
| 已有 PR 不在列表 | 插件只捕获事件驱动的任务；不会回填所有历史 PR。用新的授权测试 PR，或由管理员按宿主支持的方式核实任务，不要伪造 Webhook 或直接改数据库 |
| head changed、草稿过期 | 草稿有效期 24 小时。head 变化要重新审阅最新任务；同一 head 草稿过期可重新 prepare，不能复用旧 head 的结论 |
| 提交后很久没出现 Review | 查 Core 任务时间线、Owner Gate、GitHub 故障和 outbox。网络异常后先查询，别反复要求重新发布 |

发现 GitHub 写入 `unknown` 时，已部署 #8 的管理员应按该 PR 附带的 `docs/operations/review-recovery.md` 先对账，再决定是否重试。没有该接口的实例先交给管理员处理，不清空数据库、不重建任务来绕过它。GitHub 无原子写入幂等键，恢复仍有极端延迟写入导致重复的风险。

## 8. 日常启动、修改与停用

配置完成后，每次只需确保 Maintune 和 HTTPS 入口运行，再双击网关启动脚本；同一路径会复用 `.private`。关掉网关终端或在终端按 Ctrl+C 会停止网关，不会停止远端 Maintune，也不会撤回已发布的 Review。

增加仓库时，分别确认 GitHub App 的仓库授权、Maintune 仓库启用/PR 审阅开关、插件 `repositories` 白名单。修改白名单后保存并重新加载插件，同时更新本地 `plugin-config.json` 留档；仅改该 JSON 文件不会自动更新运行中的插件。

换公网域名但保留凭据时，先调整 HTTPS 转发，再在 `connection.txt` 和 ChatGPT 连接中同步域名并保留原私密路径。`connection.txt` 只是给人复制的说明，不会控制反向代理；网关转发到 Core 的目标在 `gateway.json` 中。

轮换凭据时：停止网关，暂时停用插件；将 `.private` 备份并重命名到受保护位置，重新运行向导；把新 access_token 填到 Maintune，启用插件，启动网关，再用新 URL 更新客户端。不要把备份发给别人。旧 URL 应失效，并用一次只读调用核实新连接。

暂停接管新 PR 时在 Maintune 停用插件；这保留配置与数据，但已等待插件的任务需管理员按实际状态处理，不应期待自动变回内置审阅。**卸载不同于停用：当前宿主卸载会删除插件运行目录**，先停止相关进程并备份，再考虑卸载。

升级前保留 `.private` 及 Maintune 的数据和加密配置备份。插件上下文和草稿保存在插件 data 目录下的 `reviews.db`；默认位于 `data/plugins/runtime/nanaseinori.mcp-review/data/reviews.db`，自定义部署以实际路径为准。备份 SQLite 前停止写入。升级使用宿主支持的插件升级流程，保留数据；不要通过卸载重装进行无备份升级。升级后重载插件/网关，按客户端要求刷新工具定义，并先做只读验证。

## 9. 首次使用的完成标准

- Maintune 插件安装并正常运行，仓库在三处均允许：GitHub App、Maintune 仓库设置、插件白名单。
- ChatGPT 真正调用六个工具中的只读工具成功，能找到事件触发的测试任务。
- 读完可用 diff，明确缺失内容；prepare 后 GitHub 尚未出现本次 Review。
- 对话授权后提交一次；Core 策略允许时出现对应 Review，类型、head、正文和 App 作者均符合预期。
- 查询状态能说明真实结果；Owner Gate、旧 head、鉴权失败不能被绕过。

如果只完成本机显式导入的测试，不能记录为公网 Webhook 已验证；如果只通过 Python 测试，不能记录为 macOS 实机已验证。当前项目的实际验收是 Windows 上 ChatGPT 网页草稿经 Core 恢复流程完成一次 GitHub Review，公网 Webhook、macOS 实机仍待单独验收。
