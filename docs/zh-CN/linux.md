# Linux 部署

正式验收目标是 Ubuntu 24.04 LTS；Debian 12+ 尽力支持。推荐至少 2 核 CPU、4 GB 内存和 15 GB 可用空间。

## 前置条件

- Docker Engine 与 Docker Compose v2；
- `curl`、`tar`、`sha256sum`；
- 首次构建时能访问 GitHub、基础镜像仓库和 Python 包源。

## 安装

解压 Release Bundle 后执行：

```bash
chmod +x scripts/linux/*.sh
./scripts/linux/install.sh --port 8000
```

Docker 尚未安装时，可在交互终端加 `--install-docker`。脚本会再次询问，且只在 Ubuntu/Debian 使用 Docker 官方 apt 仓库。默认监听 `127.0.0.1`，管理员令牌和加密密钥生成在权限为 600 的安装目录 `.env` 中。

打开 `http://127.0.0.1:8000`，从 `.env` 读取管理员令牌并完成 Setup Wizard。公网使用时请按 [反向代理说明](../installation/reverse-proxy.md) 配置 HTTPS。

## 运维

```bash
./scripts/linux/doctor.sh
./scripts/linux/backup.sh
./scripts/linux/update.sh --version 0.1.0-preview.2
./scripts/linux/restore.sh --backup /path/to/backup
```

升级会先备份关键数据，再分阶段取得、校验和构建新版本；失败时保留旧版本、旧镜像和备份。重复安装不会覆盖已有 Secret。数据默认位于安装目录 `data/`，备份位于 `backups/`。恢复会修改持久数据，先停止写入并核对备份路径。

## 常见问题

- 健康检查失败：运行 `doctor.sh`，再检查 `docker compose logs --tail 100 maintainer`。
- 数据目录权限错误：Linux bind mount 应允许容器 UID 10001 读写。
- 首次构建超时：确认包源和基础镜像可访问，然后重新执行安装；原数据不会被删除。
- Local Sandbox 不是强隔离；运行不可信仓库应配置 Shipyard Neo。
