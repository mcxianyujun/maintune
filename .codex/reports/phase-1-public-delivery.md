# Phase 1 — 公开交付完成记录

日期：2026-09-29。范围仅限 Plugin API v2 的 Phase 1 开发者基础和已验证的公开请求边界修复；未启动 AnySearch Phase 2。

## 交付仓库

| 仓库 | 分支 | 已推送提交 | 内容 |
| --- | --- | --- | --- |
| [Maintune Core](https://github.com/mcxianyujun/maintune/tree/codex/v0.1.0-stable) | `codex/v0.1.0-stable` | `701618cd8d7d754120fd45b35fb2163b3f9594a8`（边界修复） | Agent Action 在 Core 出口仅保留插件公开 Tool schema 字段；回归测试、API reference、Phase 1 历史验收及贡献评审报告。本文档及目标状态由后续文档提交补齐。 |
| [Plugin SDK](https://github.com/mcxianyujun/maintune-plugin-sdk) | `main` | `cb8ee80e42198a0499bfd0049fb6bc175dbeb786` | README 修正公开文档链接及 Preview 3 `PluginContext` 字段描述。 |
| [Plugin Template](https://github.com/mcxianyujun/maintune-plugin-template) | `main` | `63ff29d1cdcacea23096bfa5e5dc00de6c825179` | 中英文 README 增加 `.mtp` 安装、启用、`code_worker` 授权和真实 Agent 验证步骤。 |

## 验证和 CI

- 真实 `external.checkpoint/double` Agent 调用通过：公开 SDK 构建 `.mtp`，隔离 Maintune 安装启用并授权 `code_worker`，真实 OpenHands Agent 调用 `double(21)` 一次，插件返回 42，Agent 正常报告结果。详见 `plugin-public-boundary-fix.md`。
- Core 完整后端测试：147 passed；Plugin API v2 相关测试：31 passed。中英文文档一致性：9 对通过。`release_audit.py`：PASS，当前追踪文件和 Git 历史未发现高置信密钥或禁止发行文件。暂存清单仅包含批准的代码、测试、文档和报告。
- SDK 本地测试：3 passed。[SDK CI run 36569762023](https://github.com/mcxianyujun/maintune-plugin-sdk/actions/runs/36569762023)：SUCCESS。
- Template 本地测试：2 passed。[Template CI run 36569797172](https://github.com/mcxianyujun/maintune-plugin-template/actions/runs/36569797172)：SUCCESS。
- Core 的 `CI` 工作流只对 `main` push 或 Pull Request 自动运行；本次只推送 feature branch、未创建 PR，因此该分支推送**不会触发远端 Core CI**。不得把本地测试称为该分支远端 CI 通过。

## 状态与边界

**Phase 1 public delivery：COMPLETE。** Core 修复已公开在独立分支，但**尚未进入 Core 默认分支**。截至本次交付，Core 公开 `main` 为已合并 PR #7 的 `81a00dad17a657ec28e357aae109c418e9fa41bc`；Phase 1 分支从更早基线产生，不包含该合并提交。将来若要合入 `main`，须先核对并协调这条分叉，再以 PR 触发完整 Core CI；本轮没有擅自合并或改写历史。

贡献治理已审阅：普通 AGPL-only 修复与商业再许可授权应分开处理，见 `external-contribution-review.md`。PR #8、#9 未合并。未创建 tag/Release，未部署生产，未修改 Plugin API 设计。**Phase 2：NOT STARTED；等待新的授权。**
