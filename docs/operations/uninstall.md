# 卸载

默认 uninstall 只停止并移除应用容器，保留数据、Secret、版本 bundle 和备份。只有显式传入删除数据选项时才删除持久数据。

删除前先运行 backup，并确认归档和 manifest 可读取。脚本不会删除 Docker Desktop/Engine，也不会修改其他 Compose project。
