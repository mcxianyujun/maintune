# 测试

```bash
.venv/Scripts/python -m pytest -q
cd frontend && pnpm build && pnpm smoke:preview
python scripts/release_audit.py
python scripts/build_release.py
```

CI 还验证 Compose、本地 Docker build、容器内 `pip check` 和 smoke。真实发布候选需要全新 Linux 目录完成 installer/manual Compose、Setup Wizard、OpenHands coding loop、Local 与 Shipyard Neo 验收。Windows Docker Desktop E2E 若未执行，报告必须明确标注为人工待验。
