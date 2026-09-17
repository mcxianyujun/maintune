# Windows 11 部署

## 前置条件

- Windows 11；
- Docker Desktop，启用 WSL2 backend；
- Docker Compose v2；
- PowerShell 7 推荐，Windows PowerShell 5.1 亦可解析现有脚本。

先确认 Docker Desktop 已启动：

```powershell
docker version
docker compose version
```

## 安装与首次启动

解压 Release Bundle，在其根目录运行：

```powershell
.\scripts\windows\install.ps1 -Port 8000
```

默认安装目录位于用户本地应用数据目录。脚本生成 `.env`、本地构建镜像、执行 `pip check`、启动服务并等待健康检查；不会静默安装 Docker，也不会覆盖已有 Secret。浏览器打开后，从私有 `.env` 读取管理员令牌并完成 Setup Wizard。

## 停止、启动与运维

服务由 Docker Compose 管理。进入当前版本目录后可运行 `docker compose stop` 与 `docker compose up -d --wait`。日常脚本：

```powershell
.\scripts\windows\doctor.ps1
.\scripts\windows\backup.ps1
.\scripts\windows\update.ps1 -Version 0.1.0-preview.1
.\scripts\windows\restore.ps1 -BackupPath C:\path\to\backup
```

升级先备份，再校验并构建新版本；失败时保留上一版本。不要手工删除 `data`、`.env` 或 `backups`。需要搬迁时同时备份数据目录和 `.env`，并保护其中的管理员令牌与加密密钥。

## 已知边界与排查

Windows 脚本已完成语法、路径和流程自动检查；最终 Windows 11 + Docker Desktop fresh-install 仍需人工验收。Docker 命令不可用时先启动 Docker Desktop；WSL2 资源不足时在 Docker Desktop 中增加内存；端口冲突可用 `-Port` 指定其他端口。更多信息见 [故障排查](../troubleshooting.md)。
