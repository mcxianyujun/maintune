# Maintune

自托管 GitHub 自动维护工具。

[English](README.md) | [简体中文](README.zh-CN.md)

自托管的 GitHub 仓库维护控制台。**v0.1.0-preview.1** 通过 GitHub App 接收 Issue 与 Pull Request 事件，由受控 Agent 提出修改或审核意见，再由 Controller 与确定性 Policy 执行 GitHub 写操作。

当前版本采用以 `#66CCFF` 为核心的洛天依主题默认界面：轻量、清爽，并保留长期使用所需的信息密度。页面使用本项目生成的洛天依二次元立绘与 Q 版导航图，不包含第三方官图或来源不明的搬运图；角色权利与代码许可边界见素材清单。

## Preview 能力

- Issue → 分析 → Sandbox 修复 → 测试 → 独立审核 → PR。
- 外部 PR 审核、贡献者更新后的重新审核，以及受策略约束的 Bot PR 自动合并。
- OpenAI-compatible 模型、OpenHands SDK Runtime、Local 与 Shipyard Neo Sandbox。
- Setup Wizard、任务时间线、用量、失败原因、备份与诊断。
- Windows 11、Ubuntu 24.04 和 Docker Compose 本地构建部署。

适合愿意自己部署、能审阅自动化策略，并希望试用 Issue → PR → Review → Merge 闭环的个人维护者和小团队。它仍是 Preview，不承诺无人值守运行、所有仓库都能自动修复，或插件 API 已稳定。

## 快速开始

### Windows 11

要求：Windows 11、Docker Desktop（WSL2 backend）和 Docker Compose v2。下载 Release Bundle 并检查脚本后，在 PowerShell 中运行：

```powershell
.\scripts\windows\install.ps1
```

### Linux

要求：Docker Engine、Docker Compose v2、`curl`、`tar` 与 `sha256sum`。下载 Release Bundle 并检查脚本后运行：

```bash
chmod +x scripts/linux/*.sh
./scripts/linux/install.sh
```

### Docker Compose / 手动

```bash
cp .env.example .env
# 为管理员令牌和加密密钥填入随机值
docker compose build --pull
docker compose run --rm --no-deps maintainer pip check
docker compose up -d --wait
```

打开 `http://127.0.0.1:8000` 并完成 Setup Wizard。公网部署请先配置 HTTPS 反向代理。

## 发布状态

| 组件 | Preview 状态 |
| --- | --- |
| Windows 11 安装器 | Available，真实 Docker Desktop E2E 待人工验证 |
| Linux 安装器 | Available，Ubuntu 24.04 验收目标 |
| Docker Compose | Available，本地构建 |
| 公共预构建容器 | **Not provided in v0.1.0-preview.1** |

为避免重新分发一个许可条款目前不够明确的传递 Runtime 工件，Preview 安装器会在用户机器上构建镜像，并从官方包源取得固定版本依赖。安装需要访问 GitHub、PyPI 和基础镜像仓库；Preview 不支持完整离线安装。技术说明见 [Runtime 依赖](docs/licensing/runtime-dependencies.md)。

插件系统在本版本中标记为 **Experimental**，其配置结构、界面和扩展接口仍可能变化。Windows 11 + Docker Desktop 安装流程仍属于人工验证项。

## 安全边界

Local Sandbox 只提供路径、工作目录、超时与环境限制，不是强安全隔离。处理不可信仓库应使用 Shipyard Neo。模型和外部仓库内容均不可信；GitHub 写操作由 Controller 与 Policy 决定，Sandbox 不接触 Controller 凭据。

## 文档

- [开始使用](docs/getting-started.md)
- [Linux 部署](docs/deployment/linux.md)
- [Windows 11 部署](docs/deployment/windows.md)
- [Docker Compose](docs/deployment/docker-compose.md)
- [首次设置向导](docs/first-run/setup-wizard.md)
- [Preview 发布说明](docs/preview-release.md)
- [升级、备份与诊断](docs/operations/upgrade.md)
- [安全模型](docs/security/security-model.md)
- [架构](docs/development/architecture.md)
- [故障排查](docs/troubleshooting.md)
- [界面素材与授权](docs/licensing/asset-attribution.md)

## 许可证

- **AGPL-3.0-only**：允许商业使用，前提是使用者遵守 AGPL 条款及其适用的源码提供义务。
- **商业许可证**：如需闭源、专有集成、OEM 或其他替代授权条款，可与 **mcxianyujun** 单独签订书面协议；详情见 [Commercial License](COMMERCIAL-LICENSE.md)。
- 本项目原创或生成的洛天依二创视觉素材，在项目作者拥有或控制的权利范围内使用 [CC BY-NC-SA 4.0](LICENSES/CC-BY-NC-SA-4.0.txt)。
- 洛天依 / VSINGER 的角色名称、设定、形象及底层 IP 不属于本项目的 AGPL 或 CC 授权范围，相关权利归其权利方。
- 第三方依赖继续遵循各自许可证。完整边界见 [NOTICE](NOTICE) 与 [素材授权清单](docs/licensing/asset-attribution.md)。
