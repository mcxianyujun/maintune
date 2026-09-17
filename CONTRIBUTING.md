# 贡献指南

1. 先在 Issue 中描述问题、边界和验证方法。
2. 修改应保持 Controller、Policy、Runtime、Sandbox、Provider、Notification、Plugin 与 Audit 的职责分离。
3. 不得把 Secret、数据库、日志、私钥、依赖缓存或第三方专有工件提交到仓库。
4. 后端运行 `.venv/Scripts/python -m pytest -q`；前端运行 `pnpm build`；部署修改还需验证 Compose 与相应平台脚本。
5. PR 描述应写清触发条件、修改后的行为、测试证据和已知限制。

## 贡献授权 / Contributor licensing

提交贡献即表示你有权按项目的 AGPL-3.0-only 许可证提供该贡献。AGPL 本身允许商业使用，但必须遵守其条款。

By submitting a contribution, you confirm that you have the right to provide it under AGPL-3.0-only. The AGPL itself permits commercial use subject to its terms.

项目作者不会仅凭收到 Pull Request 就假定拥有商业再许可权。Preview 阶段采用以下边界：

- 仅进入 AGPL 发行版的普通修复可以按 AGPL-3.0-only 接受；
- 计划纳入双授权核心、Commercial License、闭源集成或 OEM 版本的贡献，需要贡献者另行签署 [Contributor License Agreement](CONTRIBUTOR-LICENSE-AGREEMENT.md)；
- 如果雇主或其他主体可能拥有相关权利，贡献者需要先取得相应授权；
- 在 CLA 完成前，维护者可以保留或拒绝合并相关 PR；不会使用第三方 CLA SaaS 自动收集个人信息。

The project does not assume that receiving a Pull Request automatically grants commercial relicensing rights. Contributions intended for the dual-licensed core or a Commercial License build require the separate [Contributor License Agreement](CONTRIBUTOR-LICENSE-AGREEMENT.md). Employer authorization may also be required. Until the agreement is complete, the maintainer may hold or decline the PR. No third-party CLA SaaS is used during Preview.

流程与隐私说明见 [Contributor licensing plan](docs/licensing/contributor-licensing.md)。
