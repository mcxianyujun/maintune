# 备份

Windows 运行 `scripts/windows/backup.ps1`，Linux 运行 `scripts/linux/backup.sh`。脚本短暂停止应用，打包 `.env` 和持久数据，生成包含版本、schema 与 SHA-256 的 manifest，然后重新启动服务。

备份包含内部 Secret 和加密数据库，必须按敏感数据保存。创建后验证文件与 manifest 同时存在，并把副本存放在独立介质。
