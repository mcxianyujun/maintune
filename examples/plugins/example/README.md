# Plugin API v2 最小参考示例

这是开发者阅读、理解 API 的参考，**不是推荐的生产插件**。模板用于开始新项目，AnySearch 是用户插件；本例只展示最小公开边界。沿用已有 `example.workflow-notes` ID 和目录，不创建第二套示例。

## 结构与契约

- `manifest.yaml`：JSON 形式的合法 YAML，声明 API v2、隔离运行、Python entrypoint、普通 `label` 和顶层 `demo_secret` 配置。
- `src/workflow_notes.py`：只导入公开 SDK 和标准库；一个 Hook、一个 Tool、可选 `stop(context)` 回调。
- `tests/test_workflow_notes.py`：无需 Core 的离线测试。
- `build_mtp.py`：固定时间戳与显式文件白名单；包仅含 manifest、README、LICENSE、requirements 和源码。

启用/重载时，Core 启动独立 Python 进程，SDK 调用 `register(api)`。禁用时调用 `stop(context)` 并停止进程，配置和数据保留。本例无后台资源，stop 不做额外操作；**没有自定义 startup API**。

`context.config` 中 `label` 默认 Example。可选 `demo_secret` 只演示顶层 `secret: true`，无网络用途；Core 加密存储并在配置 API/UI 遮盖，插件不打印、不返回、不写入此值。不要填真实凭据。**不支持嵌套 Secret**。配置更新后重载，以便隔离进程读取新配置。

Core 提供 `context.data_dir`，插件自行选择存储方式。通知 Hook `task.started` 接收公开 payload，把最多 64 字符的 `task_id` 写入固定 `last-task.json`，下一次覆盖。读取可用 `json.loads((context.data_dir / "last-task.json").read_text())`。这不是历史数据库；不保存完整 payload、配置或凭据。Hook 返回 None，只观察，不替换流程、取消任务或触发 GitHub 写操作。

Tool 的本地名为 `add`，Core 赋予完整 ID `example.workflow-notes/add`。Python `a: int, b: int` 自动生成严格输入 schema，输出 `{"label": "Example", "total": 5}`。推荐 Agent 只有 `code_worker`，**推荐不等于启用**；当前 Core 只有此 Agent 能调用插件 Tool。安装不会自动全局授权。

刻意省略 Service（没有第二个插件消费者，无需重复 Tool）、Provider、UI、依赖、finalizer、工作流替换及 HTTP/MCP/WebSocket。此版本替换旧示例的 activity_count/Service 和演示 Provider/UI；旧安装仅用于开发，应禁用并用新包重新安装、重新授权 add。不要把旧示例用于生产依赖。

## 测试、构建与安装

Python 3.12+，先在单独的虚拟环境安装 [公开 SDK](https://github.com/mcxianyujun/maintune-plugin-sdk)：

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install git+https://github.com/mcxianyujun/maintune-plugin-sdk.git
python -m unittest discover -s tests -v
python build_mtp.py
```

在本目录执行。包为 `dist/workflow-notes-example.mtp`。上传到 Maintune 插件页，或放入 `data/plugins/inbox/` 扫描安装。需要 Maintune v0.1.0-preview.3+。

设置 label 和可选测试 Secret，启用插件；明确授权 `code_worker` 使用 `example.workflow-notes/add`，再让隔离测试任务调用 a=2、b=3，确认 total=5。不要为示例运行生产仓库任务。普通任务启动后可在本插件 data_dir 查看 last-task.json；禁用再启用后文件保留。Core 集成回归在仓库根运行 `python -m pytest tests/test_plugin_minimal_example.py`，覆盖真实安装、进程、Hook、Tool 和加密配置 API。

参阅 [项目模板](https://github.com/mcxianyujun/maintune-plugin-template)、[Plugin API v2](https://github.com/mcxianyujun/maintune/blob/main/docs/plugin-api-v2.md)。本例随 Core 采用 AGPL-3.0-only（见包内 LICENSE），不改变独立 SDK/模板的许可证，也不表示 Core 采用 MIT。

## English

This is a small developer reference, **not a recommended production plugin**. The template starts a project; AnySearch serves users. This example teaches the public API. It replaces the existing example in place and retains `example.workflow-notes`.

The manifest declares API v2, isolated Python execution, ordinary `label` configuration and one top-level `demo_secret`. Source imports only the public SDK and standard library. Tests run without Core. The deterministic builder packages exactly manifest, README, LICENSE, requirements and source using fixed timestamps and an explicit allowlist.

On enable/reload, Core starts an independent process and the SDK calls `register(api)`. On disable, the optional `stop(context)` callback runs and the process stops; data/config remain. No background resources or custom startup API are introduced.

`label` defaults to Example. Optional `demo_secret` demonstrates encrypted/masked config only; it is never logged, returned, persisted by the plugin or sent over a network. Use a test placeholder, never a real credential. Nested secrets are unsupported. Reload after updating config so the isolated process reads it.

Core supplies `context.data_dir`; storage belongs to the plugin. The notification Hook `task.started` writes only a bounded public task_id to `last-task.json`, overwriting the previous observation. Read it with `json.loads((context.data_dir / "last-task.json").read_text())`. No complete payload/config is stored. The Hook returns None and does not replace workflows, cancel work or perform GitHub writes.

Tool `add` becomes `example.workflow-notes/add`. Typed integer inputs generate a strict schema; its result contains label and total. Only code_worker supports plugin Tools today. Recommendations do not grant access; administrators must explicitly enable the Tool.

Service is omitted because there is no second plugin consumer and it would duplicate the Tool. Providers, UI, dependencies, finalizers, workflow replacement and HTTP/MCP/WebSocket are also omitted. This replaces the old development example's activity_count/Service and Provider/UI demonstrations. Disable/reinstall old development installations and re-grant add; do not use this example as a production dependency.

With Python 3.12+, create/activate a separate venv, install the public SDK and run the commands above from this directory. Upload `dist/workflow-notes-example.mtp` through Maintune Plugins or scan it from data/plugins/inbox. Requires Maintune v0.1.0-preview.3+. Set label and an optional test secret, enable the plugin and explicitly grant add to code_worker. An isolated test task with a=2,b=3 should return total=5. Avoid production repository tasks. A task.started observation writes last-task.json; disable/re-enable preserves it. Run `python -m pytest tests/test_plugin_minimal_example.py` at the Core repository root for real package/process/Hook/Tool/config API integration tests.

See the [SDK](https://github.com/mcxianyujun/maintune-plugin-sdk), [template](https://github.com/mcxianyujun/maintune-plugin-template), and [API reference](https://github.com/mcxianyujun/maintune/blob/main/docs/plugin-api-v2.md). This in-tree example is AGPL-3.0-only (included LICENSE); independent SDK/template licenses remain unchanged and Core does not become MIT.
