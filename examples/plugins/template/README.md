# Maintune Plugin API v2 Template

一个可直接复制为独立 GitHub Template Repository 的最小 Python 插件项目。模板只依赖 Maintune 提供的公开 `maintune-plugin-sdk`，注册一个只返回问候语的 Tool；不导入 Core 私有模块，不执行仓库代码，也不需要网络或第三方包。

## 开始使用

1. 将此目录内容复制到新仓库。
2. 修改 `manifest.yaml` 中的 `id`、`name`、`publisher`、版本和描述；将 `yourname` 替换为自己的发布者标识。
3. 按需修改 `src/main.py`，保留 `register(api)` 作为入口。Tool 可以用首个 `context` 参数访问插件上下文，其余类型注解用于生成输入 schema。
4. 先安装公开 SDK：`python -m pip install git+https://github.com/mcxianyujun/maintune-plugin-sdk.git`。也可在 Maintune Core 源码的 `sdk/maintune_plugin_sdk` 构建并安装兼容的 wheel。再运行离线测试：

   ```sh
   python -m unittest discover -s tests -v
   ```

5. 构建 `.mtp` 安装包：

   ```sh
   python build_mtp.py
   ```

默认输出为 `dist/hello-plugin.mtp`，也可以传入输出路径。构建只打包固定清单中的 manifest、README、MIT 许可、依赖说明和源码；不会打包测试、缓存或本地数据。

## 项目结构

- `manifest.yaml`：Plugin API v2 包清单。当前使用 Maintune 安全 YAML 子集可读取的 JSON 写法。
- `src/main.py`：SDK 公共 API 插件入口。
- `build_mtp.py`：生成时间戳固定的可复现 `.mtp` ZIP 包。
- `tests/`：无需网络、数据库或 Core 服务的离线测试。
- `LICENSE`：MIT License，Copyright mcxianyujun。复制模板时请按需更新版权人。

## English

This is a minimal Python project that can be copied into its own GitHub Template Repository. It depends only on Maintune's public `maintune-plugin-sdk` and registers one side-effect-free greeting Tool. It does not import Core internals, execute repository code, or require network access or third-party packages.

Copy this directory, then edit `id`, `name`, `publisher`, version, and description in `manifest.yaml`. Replace `yourname` with your publisher identifier. Implement extensions in `src/main.py` and keep `register(api)` as the entrypoint. A Tool may accept `context` first; annotations on the other parameters define its generated input schema.

Install the public SDK with `python -m pip install git+https://github.com/mcxianyujun/maintune-plugin-sdk.git`. Alternatively, build a compatible wheel from Maintune's `sdk/maintune_plugin_sdk` directory with `python -m pip wheel --no-deps --wheel-dir dist .`. Run offline checks with `python -m unittest discover -s tests -v`, then build an installable package with `python build_mtp.py`. The default output is `dist/hello-plugin.mtp`; an alternate output path can be passed as an argument. The builder includes only the explicit package files, so tests, caches, and local data stay out of the archive.

The public SDK requires Python 3.12 or newer. Maintune stages the SDK into the isolated plugin environment. This template has no third-party runtime dependencies. The MIT license names mcxianyujun as its initial copyright holder; update it when publishing your own derivative.
