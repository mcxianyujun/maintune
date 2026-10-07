"""Exercise a disposable candidate container, with CI-only credentials."""
from __future__ import annotations

import json
import os
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


BASE = "http://127.0.0.1:18000"
OPENER = build_opener(ProxyHandler({}))
TOKEN = os.environ["MAINTUNE_CI_ADMIN_TOKEN"]


def call(path: str, method: str = "GET", payload: dict | None = None, auth: bool = True):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + TOKEN
    data = json.dumps(payload).encode() if payload is not None else None
    with OPENER.open(Request(BASE + path, data=data, method=method, headers=headers), timeout=60) as response:
        return json.loads(response.read())


def main() -> None:
    for _ in range(60):
        try:
            health = call("/healthz", auth=False)
            break
        except URLError:
            time.sleep(2)
    else:
        raise SystemExit("Candidate container health timeout")
    assert health == {"status": "ok", "version": "0.1.0", "schema": 4}, health
    assert call("/api/capabilities")["plugins"] is True
    for filename, plugin_id, config in (
        ("maintune-plugin-astrbot-0.1.0-preview.1.mtp", "official.astrbot-bridge",
         {"bridge_token": "ci-only-bridge-token-000000000000000000000001"}),
        ("minimal-example.mtp", "example.workflow-notes", {"label": "Container RC"}),
    ):
        call("/api/plugins/install/" + filename, "POST")
        call("/api/plugins/" + plugin_id + "/config", "PUT", config)
        call("/api/plugins/" + plugin_id + "/enable", "POST")
        plugin = next(item for item in call("/api/plugins") if item["id"] == plugin_id)
        assert plugin["enabled"] and plugin["runtime_status"] == "running", plugin_id
        assert "ci-only-bridge-token-" not in json.dumps(plugin)
        call("/api/plugins/" + plugin_id + "/disable", "POST")
        plugin = next(item for item in call("/api/plugins") if item["id"] == plugin_id)
        assert not plugin["enabled"] and plugin["runtime_status"] == "stopped", plugin_id
        print("Candidate isolated plugin lifecycle: PASS", plugin_id)
    print("Candidate container health/schema/capabilities/v1+v2 loading: PASS")


if __name__ == "__main__":
    main()
