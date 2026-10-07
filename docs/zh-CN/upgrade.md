# 升级

运行平台对应的 `update` 脚本并指定目标版本。流程先备份，再下载和校验 Release Bundle、本地构建新镜像、保留原数据、运行迁移、重建服务并做健康检查。

失败时原版本 bundle、原镜像和备份会保留。不要自动执行数据库降级；根据输出使用 restore 脚本恢复。代理环境变量会传给 Docker build。

## Preview 3 → v0.1.0 Stable 候选版

候选版尚未发布，不应期待 v0.1.0 下载地址已经存在。隔离验收使用已核验的 RC 源码包，并传入 Linux `--source-dir` 或 Windows `-SourceDirectory`。正式发布后，升级脚本指定版本 `0.1.0`。

数据库继续使用 schema v4，本次 Stable 不新增迁移。原 `.env`、加密密钥、数据库、插件配置和 `data/plugins/data/` 需一起保留并提前备份；已有 Secret 解密依赖原加密密钥。既有 v1 `.mtp` 兼容，v2 Agent Tool 仍只支持 `code_worker`。未知 GitHub 写入应先由管理员核对恢复，再重试，参见[审核恢复](../operations/review-recovery.md)。本次 RC 审计不执行生产升级。
