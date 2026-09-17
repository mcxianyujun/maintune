# Linux

正式目标为 Ubuntu 24.04 LTS，Debian 12+ 尽力支持。安装 Docker Engine 与 Compose v2，然后：

```bash
chmod +x scripts/linux/*.sh
./scripts/linux/install.sh --port 8000
```

若 Docker 缺失，可在交互模式显式传 `--install-docker`；脚本会再次询问，并使用 Docker 官方 apt 仓库。非交互模式不会自动安装 Docker。重复运行会保留数据库、历史和 Secret。
