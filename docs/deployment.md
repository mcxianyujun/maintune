# 实际部署

- 服务器：`47.77.219.0`，Ubuntu 24.04.2 LTS。
- 域名：<https://maintainer.erichmc.bond>。
- 应用目录：`/opt/ai-maintainer`。
- 应用容器仅映射 `127.0.0.1:8000`；Caddy 提供公网 80 → 443 重定向与 HTTPS。
- 管理令牌和加密主密钥保存在服务器 `/opt/ai-maintainer/.env`（0600）。不要把该文件提交到 Git。
- 本机登录令牌交付位置：`data/server-admin-token.txt`（已忽略 Git，仅当前 Windows 用户可读）。这份文件只含管理员登录令牌，不含加密主密钥。

## 运维

```sh
cd /opt/ai-maintainer
docker compose -f compose.yaml -f compose.https.yaml ps
docker compose -f compose.yaml -f compose.https.yaml logs --tail 50
docker compose -f compose.yaml -f compose.https.yaml up -d --build --wait
```

Caddy 自动续期证书；DNS 保持指向该服务器，80/443 端口保持可达。[Caddy 官方说明](https://caddyserver.com/docs/automatic-https)

## 更新与备份

更新前备份应用数据库 volume（应用停机或 SQLite backup API 生成一致快照），并单独安全备份 `.env`。备份必须包含解密主密钥，否则数据库中的 Provider Key 无法恢复。还应备份 Caddy data volume，避免不必要的证书重复申请。

源码在本机仓库；前端修改后先 `pnpm build`，上传构建文件和后端，再构建应用镜像。不要覆盖 `.env`，不要执行 `down -v`。

升级前，先使用 SQLite backup API 生成一致快照并复制 `.env`，核对备份哈希后再构建。schema v3 新增运行配置快照表，并把旧模型字符串和旧 steps/timeout JSON 原位升级；schema v4 添加 `config_audit`，用于记录不含密钥的配置重置事件。两次迁移均不删除 Provider、Agent prompt、GitHub、Sandbox、仓库或任务历史。若要回滚到不认识新 JSON 的旧版本，必须同时恢复升级前数据库和对应代码备份。OpenHands 的可写目录位于 `/app/data/openhands`。

部署后除 `/healthz` 外，还应登录控制台检查 GitHub 接入、受管仓库和维护任务页面。真实自动化必须等 GitHub App 安装、Webhook delivery、专用测试仓库和 SMTP 验收通过后启用。
