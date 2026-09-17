# 备份

Windows 运行 `scripts/windows/backup.ps1`，Linux 运行 `scripts/linux/backup.sh`。脚本短暂停止应用，打包 `.env` 和持久数据，生成包含版本、schema 与 SHA-256 的 manifest，然后重新启动服务。

备份包含内部 Secret 和加密数据库，必须按敏感数据保存。创建后验证文件与 manifest 同时存在，并把副本存放在独立介质。


# 恢复

Restore 会校验 manifest 中的 SHA-256，停止服务，将当前数据替换为备份中的标准 `data` 目录和 `.env`，再启动并等待健康检查。

这是破坏性操作，必须显式使用 `-Force` 或 `--force`。恢复前保留当前备份，不要把旧 schema 数据自动降级到更早应用版本。
