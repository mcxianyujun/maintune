# Docker Compose 本地构建

Release Bundle 包含 Dockerfile、固定 `requirements.lock`、应用源码和已构建前端。准备 `.env` 后执行：

```bash
mkdir -p data
sudo chown -R 10001:10001 data   # Linux bind mount; Windows Docker Desktop 可跳过
docker compose build --pull
docker compose run --rm --no-deps maintainer pip check
docker compose up -d --wait
curl --fail http://127.0.0.1:8000/healthz
```

依赖文件先于应用源码复制，以复用 Docker layer cache。镜像只保存在本机；不要把它推送到公开 registry。数据默认绑定到安装目录 `data`，升级和卸载不得使用会删除数据的选项。
