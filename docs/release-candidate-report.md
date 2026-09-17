# v0.1.0-preview.1 Release Candidate 验收报告

验收日期：2026-09-17  
发布方式：源码 Release Bundle + 用户本机 Docker 构建  
结论：**Release Candidate 已通过当前可自动化的发布前检查；公开发布仍等待维护者明确说“发布”。**

## 功能与界面

- 九步 Setup Wizard、Dashboard、任务、仓库、模型、Agents、GitHub、Sandbox、通知与系统设置页面完成。
- Chrome 全新 context 在 1920、1280 和 390 像素视口完成本地浏览器验收，无控制台错误或失败请求。
- 生产公网 `https://maintainer.erichmc.bond` 验证登录控件、认证后概览与高级配置页面均实际渲染；Console error 和 failed request 均为 0。
- 公网入口 HTML 返回 200、`text/html` 和 `no-cache, no-store, must-revalidate`；哈希 JS/CSS 返回 200、正确 MIME 和一年 `immutable` 缓存。
- 默认界面以 `#66CCFF` 为核心，并加入本项目生成的洛天依二次元立绘与十枚 Q 版导航图。它们不是官方素材；角色权利和非商业 Preview 使用边界已在素材清单中单独记录。
- 源代码使用 AGPL-3.0-only，并可与 mcxianyujun 单独协商替代 Commercial License；项目原创/生成的洛天依二创视觉素材在作者拥有或控制的权利范围内使用 CC BY-NC-SA 4.0。洛天依 / VSINGER 底层 IP 明确排除在两者之外。

## Runtime dependency distribution

| 项目 | 结果 |
| --- | --- |
| OpenHands SDK | `1.47.0`，固定于 `requirements.lock` |
| lmnr | `0.7.62`，由固定依赖树安装 |
| lmnr-claude-code-proxy | `0.1.24`，由固定依赖树安装 |
| 依赖来源 | Docker build 时从第三方官方 Python package index 获取 |
| 包含于 Release Bundle | **NO** |
| 包含于 public prebuilt image | **NO**；本 Preview 不提供公共预构建镜像 |
| 用户取得方式 | 安装器在用户机器执行 local Docker build |
| `pip check` | `No broken requirements found.` |
| 最终镜像依赖报告 | 146 个已安装 distribution；freeze 与 license metadata 报告已生成 |

源码包扫描确认没有 wheel、sdist、Python cache、`.env`、数据库、日志、备份、私钥或预构建容器。许可证审计接受 source/local-build 分发；公共预构建镜像继续禁用。

## Runtime fresh-build 验收

- Ubuntu 24.04 隔离目录从源码包执行首次无缓存本地构建，约 137 秒完成。
- 容器内 `pip check` 和 `import openhands.sdk` 通过。
- 使用生产当前 `code_worker`、模型供应商和 Runtime 配置完成真实隔离 coding task：读取错误实现、运行失败测试、写入修复、再次运行测试，共 5 个工具步骤、10,383 tokens。
- 工具证据同时包含 `read_file`、`write_file` 和 `shell`；最终测试通过。
- Local Sandbox 创建、文件读写、命令执行和销毁通过。
- Shipyard Neo 创建、文件读写、命令/测试执行和销毁通过。
- 诊断日志未包含实际 Provider API Key，临时诊断日志已删除。

## Installer

| 路径 | 结果 |
| --- | --- |
| Linux local build | Ubuntu 24.04 fresh install 通过 |
| Windows local build | PowerShell 全部脚本解析通过；真实 Windows 11 + Docker Desktop E2E 仍需人工验证 |
| Manual Compose | 从最终源码包配置、构建、`pip check`、启动和健康检查通过 |
| 完整 Linux 构建 | 两次实测约 137 秒与 153 秒，平均约 145 秒 |
| 第二次安装 | 数据库与 `.env` 哈希保持不变；缓存重建约 8.75 秒 |
| 再次手动构建 | 缓存构建约 1.15 秒 |
| 校验和失败 | 在解压、构建和服务变更前停止，原安装保持可用 |
| 网络失败与重试 | 下载使用 curl fail-fast + 3 次重试和 2 秒间隔；构建失败不会删除旧版本、旧镜像或备份 |

Backup、Restore、Doctor 和幂等安装路径已在 Ubuntu 验证。Restore 能恢复测试标记删除前的数据；重复安装不重置管理员令牌、加密密钥、数据库或已有配置。

## Production deployment

- 生产从旧 `ai-maintainer:0.2.0` 升级到本地构建的 `ai-maintainer:0.1.0-preview.1`，健康接口报告 schema 4。
- 升级前创建源码、Compose 和持久数据备份，并保留旧镜像与恢复材料。
- Providers、Agents、Settings、Sandbox、GitHub、Email、Repositories、Tasks、Runs、Runtime configs 和 Config audit 共 11 组 API 数据在升级前后数量与 SHA-256 完全一致。
- Setup Wizard 的 database、model、GitHub、sandbox、runtime 和 repository 六项生产诊断全部通过。
- Production Doctor 验证 Compose、health、`pip check`、OpenHands import 与数据磁盘状态。

## 自动化验证

- Backend：67 项 pytest 通过。
- Frontend：TypeScript/Vite production build 通过，47 modules transformed；透明 WebP 主题素材共约 0.53 MB。
- Compose config、Linux shell syntax、Windows PowerShell parse 通过。
- Release audit 与 source-only bundle scan 通过；从最终镜像生成确定性的 CycloneDX Runtime SBOM。
- CI 构建镜像仅作临时测试，不上传镜像 artifact，也不推送 registry。

## 已知限制

- **Prebuilt GHCR: NOT PROVIDED IN v0.1.0-preview.1.** 这符合 Preview 的 local-build 分发策略，不是发布 blocker。
- Windows 脚本已完成静态解析和逻辑检查，但真实 Windows 11 + Docker Desktop fresh-install E2E 仍是人工验收项，因此 README 明确标注。
- Preview 不支持完整离线安装；首次构建必须访问 GitHub、PyPI 与基础镜像仓库。
- Local Sandbox 不是强隔离环境；处理不可信仓库应使用 Shipyard Neo。
- 插件系统标记为 Experimental，配置结构和扩展 API 仍可能变化。

## 发布边界

维护者已明确授权在全部最终门禁通过后发布 `v0.1.0-preview.1` Pre-release。GHCR 预构建镜像继续禁止发布。
