# Docker Compose 部署

Compose 方案包含一个 Maintainer 应用服务。SQLite 数据库、加密配置、OpenHands 持久文件和运行记录保存在绑定目录 `data/`；镜像从固定的 `requirements.lock` 和当前源码在本机生成。

## 准备环境

```bash
cp .env.example .env
mkdir -p data
```

必须设置 `MAINTAINER_ADMIN_TOKEN` 与 `MAINTAINER_ENCRYPTION_KEY`。Linux 上让容器 UID 10001 可写数据目录：

```bash
sudo chown -R 10001:10001 data
```

## 构建、启动和检查

```bash
docker compose build --pull
docker compose run --rm --no-deps maintainer pip check
docker compose up -d --wait
curl --fail http://127.0.0.1:8000/healthz
```

默认只面向本机。公网入口必须使用 HTTPS 反向代理，并保留应用对入口 HTML 和哈希静态资源的缓存策略。

## 停止、升级、备份

```bash
docker compose stop
docker compose down
```

`docker compose down` 不要附加 `-v`。升级前复制 `data/` 和 `.env` 到受保护位置，取得新源码后重新执行 build、`pip check` 和 `up -d --wait`。恢复时先停止服务，保存当前数据副本，再还原同一组数据与 `.env`。生产环境推荐使用平台文件系统快照，并验证恢复后的 `/healthz` 和 Setup Wizard 诊断。

## 主要变量

| 变量 | 用途 |
| --- | --- |
| `MAINTAINER_ADMIN_TOKEN` | Web 控制台管理员凭据 |
| `MAINTAINER_ENCRYPTION_KEY` | 服务端 Secret 加密密钥 |
| `MAINTAINER_BIND_ADDRESS` | 监听地址，默认 `127.0.0.1` |
| `MAINTAINER_PORT` | 映射端口，默认 8000 |
| `MAINTAINER_DATA_DIR` | 持久数据目录 |

不要提交 `.env`、数据目录、日志、备份或诊断输出中的 Secret。
