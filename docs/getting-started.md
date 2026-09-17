# 开始使用

选择 Windows 11 安装器、Linux 安装器或手动 Compose。安装器会下载固定 Release Bundle、校验 SHA-256、保留数据目录和 Secret、在本机构建镜像、运行 `pip check`、启动服务并等待健康检查。

首次登录使用安装目录 `.env` 中的 `MAINTAINER_ADMIN_TOKEN`。随后按向导配置模型、GitHub App、Sandbox 和至少一个仓库。管理员页面只应通过 HTTPS 或 SSH 隧道访问。

安装前确保能访问 Release 下载地址、PyPI 和 Docker 基础镜像仓库。代理可通过标准 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 环境变量传给构建。
