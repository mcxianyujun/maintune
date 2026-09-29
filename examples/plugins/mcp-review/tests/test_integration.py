# SPDX-License-Identifier: MIT
"""Actual Core, isolated SDK process, HTTP gateway, and official MCP client.

Only GitHub/model calls are replaced. No real credentials or remote writes.
"""
import asyncio
import http.client
import json
import shutil
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from maintainer.api import create_app
from maintainer.db import Repository, Task
from maintainer.security import Settings

from build_mtp import build
from gateway import make_server
from test_plugin import HEAD, TOKEN, draft

PLUGIN = "nanaseinori.mcp-review"


def local_client(**kwargs):
    return httpx.AsyncClient(**kwargs, trust_env=False, follow_redirects=False)


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


class GitHub:
    def __init__(self):
        self.head = HEAD
        self.reviews = []
        self.body = "Correct existing behavior"

    async def repository_guidance(self, *args):
        return ""

    async def pull_context(self, *args):
        return {"pull": {"title": "Fix parser bug", "body": self.body, "draft": False,
                         "user": {"login": "contributor", "type": "User"}, "head": {"sha": self.head}, "base": {"ref": "main"}},
                "files": [{"filename": "src/parser.py", "patch": "@@ -1 +1 @@\n-bad\n+good", "status": "modified"}],
                "commits": [{"sha": self.head}], "checks": {"check_runs": []}, "statuses": {"state": "success", "statuses": []}}

    async def review(self, installation, repo, number, sha, event, body, comments):
        self.reviews.append({"head": sha, "event": event, "body": body, "comments": comments})
        return {"id": 42, "html_url": "https://example.test/review/42"}


@pytest.fixture
def instance(tmp_path):
    app = create_app(Settings(admin_token="admin" * 10, encryption_key=Fernet.generate_key().decode(),
        database_url=f"sqlite:///{tmp_path / 'core.db'}", workspace_root=str(tmp_path / "work"),
        plugin_root=str(tmp_path / "plugins"), static_dir=str(tmp_path / "static")))
    with TestClient(app) as client:
        async def stop_worker():
            app.state.worker_stop.set()
            await app.state.worker
        client.portal.call(stop_worker)
        client.headers["Authorization"] = "Bearer " + "admin" * 10
        package = build()
        shutil.copyfile(package, app.state.plugins.packages.inbox / package.name)
        assert client.post("/api/plugins/install/" + package.name).status_code == 201
        configured = client.put(f"/api/plugins/{PLUGIN}/config", json={"access_token": TOKEN, "repositories": ["owner/repo"], "review_bot": "Qiyuanqiii"})
        assert configured.status_code == 200
        assert TOKEN not in configured.text
        response = client.post(f"/api/plugins/{PLUGIN}/enable")
        assert response.status_code == 200, response.text
        github = GitHub()
        app.state.processor.app_client = lambda: github
        async def no_model(*args):
            raise AssertionError("The model must not be called by this test")
        async def no_notify(*args):
            pass
        app.state.processor.structured_agent = no_model
        app.state.processor.notify = no_notify
        with app.state.sessions.begin() as db:
            db.add(Repository(full_name="owner/repo", installation_id=7, data={}))
            task = Task(kind="pull_request", repository="owner/repo", number=5, event="pull_request.opened",
                        delivery_id="isolated-test", status="running", data={"installation_id": 7})
            db.add(task)
            db.flush()
            task_id = task.id
        def process():
            client.portal.call(app.state.processor.process_pull, task_id, github, 7, "owner/repo", 5, {"default_branch": "main"})
        process()
        with app.state.sessions() as db:
            assert db.get(Task, task_id).status == "waiting_for_plugin"

        # Bridge real sockets to the real ASGI host without running its task worker.
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = self.rfile.read(int(self.headers["Content-Length"]))
                response = client.post(self.path, content=payload, headers={"Content-Type": "application/json", "Authorization": self.headers.get("Authorization", "")})
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            def log_message(self, *args):
                pass
        with serving(ThreadingHTTPServer(("127.0.0.1", 0), Upstream)) as upstream_port:
            config = {"maintune_url": f"http://127.0.0.1:{upstream_port}", "access_token": TOKEN, "path_secret": "s" * 43}
            with serving(make_server(config, port=0)) as port:
                yield app, client, github, task_id, process, f"http://127.0.0.1:{port}/{'s' * 43}/mcp"


def unpack(result):
    assert not result.isError, result
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("verdict,expected", [("approved", "reviewed"), ("changes_required", "waiting_for_contributor"), ("owner_decision", "waiting_for_owner")])
def test_full_flow_and_owner_gate(instance, verdict, expected):
    app, client, github, task_id, process, url = instance
    async def scenario():
        async with streamablehttp_client(url, httpx_client_factory=local_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == 6
                reviews = unpack(await session.call_tool("list_reviews", {}))
                identifier = reviews["reviews"][0]["id"]
                assert unpack(await session.call_tool("read_review", {"review_id": identifier}))["context"]["head_sha"] == HEAD
                assert "+good" in unpack(await session.call_tool("read_file", {"review_id": identifier, "file_index": 0}))["patch"]
                prepared = unpack(await session.call_tool("prepare_review", draft(identifier, verdict=verdict)))
                assert not github.reviews
                args = {"preview_id": prepared["preview_id"], "user_authorized": True}
                assert unpack(await session.call_tool("submit_review", args))["core"]["status"] == "queued"
                await asyncio.to_thread(process)
                status = unpack(await session.call_tool("review_status", {"review_id": identifier}))
                assert status["task"]["status"] == expected
                await session.call_tool("submit_review", args)
                if verdict == "owner_decision":
                    assert github.reviews == []
                else:
                    assert len(github.reviews) == 1
                    assert github.reviews[0]["event"] == ("APPROVE" if verdict == "approved" else "REQUEST_CHANGES")
                    assert "This review was conducted by Qiyuanqiii's review bot, using the model GPT-6 Astra." in github.reviews[0]["body"]
                assert client.post(f"/api/plugins/{PLUGIN}/disable").status_code == 200
                assert client.post(f"/api/plugins/{PLUGIN}/enable").status_code == 200
                assert unpack(await session.call_tool("list_reviews", {}))["reviews"][0]["state"] == "submitted"
    asyncio.run(scenario())




def test_auth_origin_protocol_and_stale_after_submission(instance):
    app, client, github, _, process, url = instance
    with httpx.Client(trust_env=False) as direct:
        assert direct.post(url.replace("s" * 43, "wrong"), json={}).status_code == 404
        assert direct.post(url, json={}, headers={"Origin": "https://untrusted.test"}).status_code == 403
        assert direct.get(url).status_code == 405
        assert direct.post(url, content="no-json", headers={"Content-Type": "text/plain"}).status_code == 415
        assert direct.post(url, json={}, headers={"MCP-Protocol-Version": "unknown"}).status_code == 400
    # The gateway rejects the declared size before reading a body. Sending the
    # entire body while it closes can cause a Windows TCP reset to hide the 413.
    target = urlsplit(url)
    oversized = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        oversized.putrequest("POST", target.path)
        oversized.putheader("Content-Type", "application/json")
        oversized.putheader("Content-Length", str(256 * 1024 + 1))
        oversized.endheaders()
        assert oversized.getresponse().status == 413
    finally:
        oversized.close()
    assert client.post(f"/api/plugins/{PLUGIN}/public/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    async def scenario():
        async with streamablehttp_client(url, httpx_client_factory=local_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                identifier = unpack(await session.call_tool("list_reviews", {}))["reviews"][0]["id"]
                preview = unpack(await session.call_tool("prepare_review", draft(identifier)))
                unpack(await session.call_tool("submit_review", {"preview_id": preview["preview_id"], "user_authorized": True}))
                github.head = "b" * 40
                await asyncio.to_thread(process)
                assert not github.reviews
                status = unpack(await session.call_tool("review_status", {"review_id": identifier}))
                assert status["task"]["status"] == "waiting_for_plugin"
                assert status["submission_state"] == "superseded"
                rows = unpack(await session.call_tool("list_reviews", {}))["reviews"]
                assert rows[0]["head"] == github.head
    asyncio.run(scenario())
