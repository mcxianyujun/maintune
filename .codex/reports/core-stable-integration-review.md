# Core Stable Phase 1 集成评审

日期：2026-09-29。目标：评估 `codex/v0.1.0-stable` → `main`，仅准备 PR；本报告不授权合并、发布或启动 Phase 2。

## 提交比较

- `main`：`81a00dad17a657ec28e357aae109c418e9fa41bc`。
- `codex/v0.1.0-stable`：`7cec728c5eef478e2e47eb8bc5f03935e01e5361`。
- 共同祖先：`866868f0f273d1cb3dc92604602e1b6595b8cf6e`（已发布 Preview 3 基线）。
- `main` 独有：PR #7 的 `51265e0a9010fffb2355db2f51030a5e4b85a3cc` 和普通合并提交 `81a00da`。
- 稳定版分支独有 8 个 Phase 1 提交：`f6c9990`、`f499a68`、`413ef1f`、`7efdfd7`、`5ec1c9e`、`ec66103`、`701618c`、`7cec728`。`git cherry -v origin/main origin/codex/v0.1.0-stable` 全部为 `+`，未发现与 `main` 等价的重复补丁。

## 合并结果和范围

`git merge-tree --write-tree origin/main origin/codex/v0.1.0-stable` 成功，生成的模拟合并树为 `2c1eb0288c9e0afc2ca084929133dd24abe1d7e7`，无内容冲突。

- PR #7 的关键文件 `backend/maintainer/plugin_system.py` 在 `main` 与模拟合并树中 blob 均为 `3ed729cdbf1803d24a8676a85c3188abfcf335f2`，证明其 1 MiB subprocess reader 修复未被旧分支覆盖。
- 边界修复提交 `701618c` 在稳定版分支，模拟合并后的 `backend/maintainer/runtime.py` blob 为 `5852657ee424d3dfe30646aea1a9e33c646016cd`，不同于 `main` 的 `7b9aeb411454cd9ef4f9c1d744841233461b5e57`；公开 Tool 参数过滤得到保留。
- 模拟合并相对 `main` 仅改变 17 个 Phase 1 文件：`.codex` 目标/报告、Plugin API 开发文档、SDK 与模板元数据/文档/测试、`runtime.py` 与边界回归测试。`plugin_system.py` 不在最终差异中；没有新功能、Issue/PR 工作流改动、数据库迁移或发布配置改动。

## CI 与合并建议

创建 PR 后必须等待当前 `CI` 的 `test` 与 `windows-scripts` 成功。`test` 应完整执行 `pip check`、全量 pytest、release audit、前端构建、Compose 校验、Docker 构建、容器 pip check、SBOM 和容器 health smoke。尤其应关注 PR #7 的大消息读取回归与本分支真实 Tool 参数回归在同一合并结果上通过。此前单独的本地/分支验证不能替代 PR CI。

建议使用**普通 merge commit**，保留已发布 Preview 3 基线、PR #7 的既有合并历史和 Phase 1 的审计提交；不需要 rebase、force-push 或 squash。当前只创建供评审的 PR，**不合并**。PR #8/#9 保持原状态；Phase 2 未启动。
