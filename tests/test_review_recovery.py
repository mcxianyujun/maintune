# SPDX-License-Identifier: MIT
"""Real admin routes and SQLite outbox, with all remote writes simulated."""
import asyncio
import copy
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from maintainer.api import create_app
from maintainer.db import Outbox, Repository, Task, Timeline
from maintainer.github import GitHubAppClient, GitHubError
from maintainer.review_recovery import RecoveryConflict, RecoveryDecision, recover_review
from maintainer.security import Settings

HEAD = "a" * 40
PAYLOAD = {"commit_id": HEAD, "event": "APPROVE", "body": "Reviewed the full diff. No blocking findings.", "comments": []}
KEY = f"pr-review:owner/repo:5:{HEAD}:APPROVE"


class GitHub:
    def __init__(self):
        self.head, self.rows, self.comments, self.writes = HEAD, [], [], []
        self.error = None
        self.pause = None

    def published(self, **changes):
        return {"id": 42, "html_url": "https://github.com/owner/repo/pull/5#pullrequestreview-42",
                "user": {"login": "review-app[bot]", "type": "Bot"}, "commit_id": HEAD,
                "state": "APPROVED", "submitted_at": "2026-09-29T00:00:00Z", "body": PAYLOAD["body"], **changes}

    async def request(self, installation, method, path, **kwargs):
        assert installation == 7 and method == "GET"
        if self.pause:
            await self.pause()
        if self.error:
            raise self.error
        return {"state": "open", "draft": False, "merged": False, "head": {"sha": self.head}}

    async def review_author(self):
        return "review-app[bot]"

    async def paginated(self, installation, path, **kwargs):
        assert installation == 7
        return self.comments if path.endswith("/comments") else self.rows

    async def publish(self):
        self.writes.append(copy.deepcopy(PAYLOAD))
        self.rows = [self.published()]
        return self.rows[0]


@pytest.fixture
def case(tmp_path):
    app = create_app(Settings(admin_token="a" * 40, encryption_key=Fernet.generate_key().decode(),
        database_url=f"sqlite:///{tmp_path / 'core.db'}", workspace_root=str(tmp_path / "work"),
        plugin_root=str(tmp_path / "plugins"), static_dir=str(tmp_path / "static")))
    with TestClient(app) as client:
        async def stop():
            app.state.worker_stop.set()
            await app.state.worker
        client.portal.call(stop)
        client.headers["Authorization"] = "Bearer " + "a" * 40
        github = GitHub()
        app.state.processor.app_client = lambda: github
        with app.state.sessions.begin() as db:
            db.add(Repository(full_name="owner/repo", installation_id=7, data={"enabled": True, "auto_review_prs": True}))
            task = Task(kind="pull_request", repository="owner/repo", number=5, event="pull_request.opened",
                        delivery_id="lost-response", status="failed_environment", data={"installation_id": 7, "head_sha": HEAD})
            db.add(task)
            db.flush()
            row = Outbox(task_id=task.id, kind="pr_review", action_key=KEY, status="unknown", attempts=1,
                         created=time.time() - 300, data={"head_sha": HEAD, "event": "APPROVE", "review_request": copy.deepcopy(PAYLOAD)})
            db.add(row)
            db.flush()
            task_id, action_id = task.id, row.id
        yield app, client, github, task_id, action_id


def preview(case):
    _, client, _, task_id, _ = case
    result = client.get(f"/api/tasks/{task_id}/review-recovery")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["request"] == PAYLOAD
    return {key: data[key] for key in ("action_id", "attempts", "head_sha", "payload_sha256")} | {"reason": "Owner authorized the scoped acceptance recovery."}


def recover(case, decision):
    return case[1].post(f"/api/tasks/{case[3]}/review-recovery", json=decision)


def state(case):
    app, _, _, task_id, action_id = case
    with app.state.sessions() as db:
        return db.get(Task, task_id).status, db.get(Outbox, action_id).status, db.get(Outbox, action_id).attempts


def write(case, payload=PAYLOAD):
    app, client, github, task_id, _ = case
    return client.portal.call(app.state.processor.github_action, task_id, "pr_review", KEY,
                              {"head_sha": HEAD, "event": "APPROVE", "review_request": payload}, github.publish)


def test_reconciles_existing_review_without_post(case):
    case[2].rows = [case[2].published()]
    result = recover(case, preview(case))
    assert result.status_code == 200 and result.json()["outcome"] == "reconciled"
    assert state(case) == ("queued", "completed", 1)
    assert write(case)["html_url"].endswith("-42")
    assert case[2].writes == []


def test_explicit_retry_preserves_payload_and_only_publishes_once(case):
    decision = preview(case)
    assert recover(case, decision).status_code == 409
    assert state(case) == ("failed_environment", "unknown", 1)
    assert recover(case, {**decision, "retry_authorized": True}).status_code == 200
    assert state(case) == ("queued", "pending", 1)
    assert write(case)["id"] == 42
    write(case)
    assert case[2].writes == [PAYLOAD]
    assert state(case) == ("queued", "completed", 2)
    with case[0].state.sessions() as db:
        row = db.get(Outbox, case[4])
        assert row.data["review_request"] == PAYLOAD
        assert db.scalar(select(Timeline).where(Timeline.kind == "github_review_retry_authorized"))


def test_late_success_is_found_before_retry(case):
    assert recover(case, {**preview(case), "retry_authorized": True}).status_code == 200
    case[2].rows = [case[2].published()]
    write(case)
    assert case[2].writes == []
    assert state(case) == ("queued", "completed", 1)


@pytest.mark.parametrize("fault", ["body", "state", "pending", "duplicate", "comments", "truncated", "network", "head"])
def test_conflicts_keep_unknown_and_never_publish(case, fault):
    decision = {**preview(case), "retry_authorized": True}
    github = case[2]
    github.rows = [github.published()]
    if fault == "body": github.rows[0]["body"] = "Different review"
    if fault == "state": github.rows[0]["state"] = "DISMISSED"
    if fault == "pending": github.rows[0]["state"] = "PENDING"
    if fault == "duplicate": github.rows *= 2
    if fault == "comments": github.comments = [{"path": "x.py", "body": "unexpected", "line": 2}]
    if fault == "truncated": github.rows *= 1001
    if fault == "network": github.error = RuntimeError("credential-must-not-leak")
    if fault == "head": github.head = "b" * 40
    result = recover(case, decision)
    assert result.status_code == (502 if fault == "network" else 409)
    assert "credential-must-not-leak" not in result.text
    assert state(case) == ("failed_environment", "unknown", 1)
    assert github.writes == []


@pytest.mark.parametrize("fault", ["attempts", "payload_sha256", "head_sha", "action_id", "disabled", "installation", "recent"])
def test_stale_preview_or_revocation_cannot_retry(case, fault):
    decision = {**preview(case), "retry_authorized": True}
    if fault in decision:
        decision[fault] = 2 if fault == "attempts" else ("b" * (40 if fault == "head_sha" else 64))
    else:
        with case[0].state.sessions.begin() as db:
            if fault == "disabled": db.get(Repository, "owner/repo").data = {"enabled": False, "auto_review_prs": True}
            if fault == "installation": db.get(Repository, "owner/repo").installation_id = 8
            if fault == "recent": db.get(Outbox, case[4]).created = time.time()
    assert recover(case, decision).status_code == 409
    assert state(case) == ("failed_environment", "unknown", 1)


def test_other_author_is_not_adopted(case):
    case[2].rows = [case[2].published(user={"login": "human", "type": "User"})]
    result = case[1].get(f"/api/tasks/{case[3]}/review-recovery")
    assert result.json()["outcome"] == "not_found"
    assert state(case)[1] == "unknown"


def test_admin_auth_strict_authorization_and_ordinary_retry_guard(case):
    decision = preview(case)
    path = f"/api/tasks/{case[3]}/review-recovery"
    assert case[1].get(path, headers={"Authorization": ""}).status_code == 401
    assert case[1].post(path, json=decision, headers={"Authorization": ""}).status_code == 401
    assert recover(case, {**decision, "retry_authorized": "true"}).status_code == 422
    assert case[1].post(f"/api/tasks/{case[3]}/retry").status_code == 409


def test_concurrent_recovery_and_cancellation_keep_action_protected(case):
    decision = RecoveryDecision(**preview(case), retry_authorized=True)
    app, client, github, task_id, _ = case
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def pause():
            entered.set()
            await release.wait()
        github.pause = pause
        first = asyncio.create_task(recover_review(app.state.processor, task_id, decision))
        await entered.wait()
        with pytest.raises(RecoveryConflict):
            await recover_review(app.state.processor, task_id, decision)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    client.portal.call(scenario)
    assert state(case) == ("failed_environment", "unknown", 1)
    assert github.writes == []


def test_legacy_payload_reconstruction_is_limited_to_clean_approval(case):
    with case[0].state.sessions.begin() as db:
        action = db.get(Outbox, case[4])
        action.data = {"head_sha": HEAD, "event": "APPROVE"}
        event = Timeline(task_id=case[3], kind="pr_review_completed", timestamp=action.created - 1,
                         data={"head_sha": HEAD, "verdict": "approved", "summary": PAYLOAD["body"], "blocking_issues": [], "suggestions": []})
        db.add(event)
        db.flush()
        event_id = event.id
    preview(case)
    with case[0].state.sessions.begin() as db:
        event = db.get(Timeline, event_id)
        event.data = {**event.data, "suggestions": [{"message": "Do not infer the old inline payload"}]}
    assert case[1].get(f"/api/tasks/{case[3]}/review-recovery").status_code == 409


def test_changed_payload_cannot_use_retry_authorization(case):
    assert recover(case, {**preview(case), "retry_authorized": True}).status_code == 200
    with pytest.raises(RecoveryConflict):
        write(case, {**PAYLOAD, "body": "Changed after approval"})
    assert state(case)[1:] == ("pending", 1)
    assert case[2].writes == []


def test_two_workers_cannot_send_two_posts(case):
    assert recover(case, {**preview(case), "retry_authorized": True}).status_code == 200
    app, client, github, task_id, _ = case
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def post():
            entered.set()
            await release.wait()
            return await github.publish()
        data = {"head_sha": HEAD, "event": "APPROVE", "review_request": PAYLOAD}
        first = asyncio.create_task(app.state.processor.github_action(task_id, "pr_review", KEY, data, post))
        await entered.wait()
        with pytest.raises(RuntimeError):
            await app.state.processor.github_action(task_id, "pr_review", KEY, data, post)
        release.set()
        await first
    client.portal.call(scenario)
    assert github.writes == [PAYLOAD]


@pytest.mark.parametrize("status,app_id,slug,valid", [
    (200, 7, "review-app", True), (403, 7, "review-app", False),
    (200, 8, "review-app", False), (200, 7, "untrusted/name", False),
])
def test_publishing_identity_is_resolved_from_authenticated_app(status, app_id, slug, valid):
    github = GitHubAppClient(7, "unused-test-key")
    github.app_jwt = lambda: "test-app-jwt"
    def handle(request):
        assert request.method == "GET" and request.url.path == "/app"
        assert request.headers["Authorization"] == "Bearer test-app-jwt"
        return httpx.Response(status, json={"id": app_id, "slug": slug})
    github.client = lambda: httpx.AsyncClient(base_url="https://api.github.test/", transport=httpx.MockTransport(handle))
    if valid:
        assert asyncio.run(github.review_author()) == "review-app[bot]"
    else:
        with pytest.raises(GitHubError):
            asyncio.run(github.review_author())


def test_restart_releases_interrupted_reconciliation_as_unknown(case):
    with case[0].state.sessions.begin() as db:
        db.get(Outbox, case[4]).status = "reconciling"
    restarted = create_app(case[0].state.settings)
    with TestClient(restarted):
        assert state(case) == ("failed_environment", "unknown", 1)
