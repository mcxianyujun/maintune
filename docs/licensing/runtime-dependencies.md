# Runtime dependencies

Maintune v0.1.0-preview.2 固定使用 OpenHands SDK 1.47.0。该 SDK 使用 MIT 许可证，但当前依赖声明会引入 `lmnr` 0.7.62，后者再声明 `lmnr-claude-code-proxy` 0.1.24。我们没有找到足够明确、可依赖的该特定工件再分发条款。

为避免重新分发一个再分发条款目前不明确的工件，Preview：

- 不把 wheel、sdist、源码副本或包缓存放进仓库和 Release Bundle；
- 不发布包含它的公共预构建 Maintune 镜像；
- 由用户在本机 Docker build 时，从第三方官方 Python package index 取得固定依赖树；
- 在镜像构建与安装流程运行 `pip check`。

第三方依赖保留自己的许可证，Maintune 的 AGPL-3.0-only 不会改变它们。此文档描述工程分发选择，不构成绝对法律结论。若上游将 Laminar observability 设为 optional，或再分发条款变得清晰，可在不改变 Setup Wizard 的情况下恢复 prebuilt image 策略。
