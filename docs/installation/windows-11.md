# Windows 11

安装 Docker Desktop，启用 WSL2 backend，确认 `docker version` 和 `docker compose version` 成功。解压 Release Bundle，在 PowerShell 中运行：

```powershell
.\scripts\windows\install.ps1 -Port 8000
```

可用参数包括 `-Version`、`-Port`、`-DataDirectory`、`-NoOpenBrowser` 和 `-NonInteractive`。脚本不会静默安装高权限软件，也不会覆盖已有 Secret。重复安装需要选择 Repair、Rebuild、Reconfigure 或 Abort。

当前开发机没有 Docker Desktop，因此 Preview 的 Windows 脚本已完成 PowerShell 解析、路径与流程检查，完整 Windows 11 Docker Desktop E2E 仍是发布前人工项目。
