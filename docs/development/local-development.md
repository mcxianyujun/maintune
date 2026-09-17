# 本地开发

需要 Python 3.12+、Node 22.12+ 和 pnpm 11。安装固定 Python lock，随后以 editable/no-deps 安装项目；前端使用 frozen lockfile。

```bash
python -m venv .venv
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cd frontend && pnpm install --frozen-lockfile && pnpm build
```

准备开发 `.env` 后运行 `uvicorn maintainer.api:create_app --factory`。开发数据与工作区应使用独立目录，不要指向生产数据库。
