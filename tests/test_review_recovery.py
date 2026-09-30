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
from maintainer.db import Outbox, Repository, ReviewFinding, Task, Timeline
from maintainer.github import GitHubAppClient, GitHubError, ingest_webhook
from maintainer.review_recovery import RecoveryConflict, RecoveryDecision, recover_review, payload_hash
from maintainer.schemas import ReviewVerdict
from maintainer.security import Settings

HEAD = "a" * 40
PAYLOAD = {"commit_id": HEAD, "event": "APPROVE", "body": "Reviewed the full diff. No blocking findings.", "comments": []}
KEY = f"pr-review:owner/repo:5:{HEAD}:APPROVE"


class GitHub:
    def __init__(self):
        self.head, self.rows, self.comments, self.writes = HEAD, [], [], []
        self.error = None
        self.pause = None
        self.review_pause = None
        self.title = "Fix calculator regression"

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

    async def pull_context(self, installation, repo, number, previous_head=""):
        assert (installation, repo, number) == (7, "owner/repo", 5)
        return {"pull": {"state": "open", "draft": False, "merged": False,
                         "title": self.title, "body": "Repair the existing behavior",
                         "user": {"login": "contributor"}, "base": {"ref": "main"},
                         "head": {"sha": self.head, "ref": "fix/calculator", "repo": {"full_name": repo}}},
                "files": [{"filename": "src/calculator.js", "patch": "@@ -1 +1 @@\n-old\n+new"}],
                "commits": [{"sha": self.head}], "checks": {"check_runs": []},
                "statuses": {"state": "success", "statuses": []}}

    async def repository_guidance(self, installation, repo, branch):
        return ""

    async def review(self, installation, repo, number, head, event, body, comments):
        assert (installation, repo, number, head) == (7, "owner/repo", 5, HEAD)
        assert {"commit_id": head, "event": event, "body": body, "comments": comments} == PAYLOAD
        if self.review_pause:
            await self.review_pause()
        return await self.publish()

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


def preview(case, expected=PAYLOAD):
    _, client, _, task_id, _ = case
    result = client.get(f"/api/tasks/{task_id}/review-recovery")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["request"] == expected
    return {key: data[key] for key in ("action_id", "attempts", "head_sha", "payload_sha256")} | {"reason": "Owner authorized the scoped acceptance recovery."}


def recover(case, decision):
    return case[1].post(f"/api/tasks/{case[3]}/review-recovery", json=decision)


def state(case):
    app, _, _, task_id, action_id = case
    with app.state.sessions() as db:
        return db.get(Task, task_id).status, db.get(Outbox, action_id).status, db.get(Outbox, action_id).attempts


def original_verdict(case):
    app, _, _, task_id, action_id = case
    with app.state.sessions.begin() as db:
        action = db.get(Outbox, action_id)
        db.add(Timeline(task_id=task_id, kind="pr_review_completed", timestamp=action.created - 1,
            data={"head_sha": HEAD, "verdict": "approved", "blocking_issues": [], "suggestions": [],
                  "summary": PAYLOAD["body"], "risk": "low", "previous_blocking_count": 0}))


def no_second_verdict(case):
    async def fail(*args, **kwargs):
        raise AssertionError("An interrupted review must not ask an Agent to regenerate the published request")
    case[0].state.processor.structured_agent = fail


def write(case, payload=PAYLOAD):
    app, client, github, task_id, _ = case
    return client.portal.call(app.state.processor.github_action, task_id, "pr_review", KEY,
                              {"head_sha": HEAD, "event": "APPROVE", "review_request": payload}, github.publish)


def webhook_task(case, delivery_id):
    app = case[0]
    payload = {"action": "opened", "repository": {"full_name": "owner/repo"},
               "pull_request": {"number": 5}, "installation": {"id": 7}}
    with app.state.sessions.begin() as db:
        _, task, _ = ingest_webhook(db, delivery_id, "pull_request", b"new delivery", payload)
        assert "head_sha" not in task.data
        return task.id


def test_first_review_write_persists_recovery_context_for_webhook_task(case):
    app, client, github, _, _ = case
    task_id = webhook_task(case, "no-prefilled-head")
    new_head = "b" * 40
    request = {**PAYLOAD, "commit_id": new_head}
    async def uncertain_write():
        raise TimeoutError("GitHub response lost")
    with pytest.raises(TimeoutError):
        client.portal.call(app.state.processor.github_action, task_id, "pr_review",
            f"pr-review:owner/repo:5:{new_head}",
            {"head_sha": new_head, "event": "APPROVE", "review_request": request}, uncertain_write)
    with app.state.sessions.begin() as db:
        task = db.get(Task, task_id)
        task.status = "failed_environment"
        assert task.data["head_sha"] == new_head
        assert task.data["review_event"] == "APPROVE"
        assert task.data["review_request_sha256"] == payload_hash(request)
        row = db.scalar(select(Outbox).where(Outbox.task_id == task_id))
        assert row.status == "unknown"
        assert {key: row.data[key] for key in ("repository", "number", "installation_id", "request_sha256")} == {
            "repository": "owner/repo", "number": 5, "installation_id": 7,
            "request_sha256": payload_hash(request)}
    github.head = new_head
    result = client.get(f"/api/tasks/{task_id}/review-recovery")
    assert result.status_code == 200, result.text
    assert result.json()["request"] == request
    github.rows = [github.published(commit_id=new_head)]
    decision = {key: result.json()[key] for key in ("action_id", "attempts", "head_sha", "payload_sha256")}
    reconciled = client.post(f"/api/tasks/{task_id}/review-recovery",
        json={**decision, "reason": "Owner reconciled the original review on its saved head."})
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["outcome"] == "reconciled"
    assert github.writes == []


def test_new_review_recovery_rejects_changed_task_context(case):
    app, client, github, _, _ = case
    task_id = webhook_task(case, "immutable-context")
    new_head = "b" * 40
    request = {**PAYLOAD, "commit_id": new_head}
    async def uncertain_write():
        raise TimeoutError("GitHub response lost")
    with pytest.raises(TimeoutError):
        client.portal.call(app.state.processor.github_action, task_id, "pr_review",
            f"pr-review:owner/repo:5:{new_head}",
            {"head_sha": new_head, "event": "APPROVE", "review_request": request}, uncertain_write)
    github.head = new_head
    with app.state.sessions.begin() as db:
        task = db.get(Task, task_id)
        task.status = "failed_environment"
        task.data = {**task.data, "review_event": "COMMENT"}
    assert client.get(f"/api/tasks/{task_id}/review-recovery").status_code == 409
    assert github.writes == []


@pytest.mark.parametrize("event", ["APPROVE", "COMMENT"])
def test_unknown_review_blocks_equivalent_new_webhook_task(case, event):
    app, client, github, _, action_id = case
    task_id = webhook_task(case, f"duplicate-{event}")
    request = {**PAYLOAD, "event": event}
    async def forbidden_write():
        raise AssertionError("second GitHub review was sent")
    with pytest.raises(RecoveryConflict):
        client.portal.call(app.state.processor.github_action, task_id, "pr_review",
            f"pr-review:owner/repo:5:{HEAD}",
            {"head_sha": HEAD, "event": event, "review_request": request}, forbidden_write)
    with app.state.sessions() as db:
        assert list(db.scalars(select(Outbox).where(Outbox.task_id == task_id))) == []
        blocked = db.scalar(select(Timeline).where(Timeline.task_id == task_id,
            Timeline.kind == "pr_review_blocked_existing_action"))
        assert blocked.data["action_id"] == action_id
    assert github.writes == []


def test_completed_review_is_reused_by_equivalent_new_webhook_task(case):
    app, client, github, _, action_id = case
    with app.state.sessions.begin() as db:
        row = db.get(Outbox, action_id)
        row.status, row.external_id, row.external_url = "completed", "42", github.published()["html_url"]
    task_id = webhook_task(case, "equivalent-completed")
    async def forbidden_write():
        raise AssertionError("second GitHub review was sent")
    result = client.portal.call(app.state.processor.github_action, task_id, "pr_review",
        f"pr-review:owner/repo:5:{HEAD}",
        {"head_sha": HEAD, "event": "APPROVE", "review_request": PAYLOAD}, forbidden_write)
    assert result["html_url"] == github.published()["html_url"]
    with app.state.sessions() as db:
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id,
            Timeline.kind == "pr_review_reused"))
        assert list(db.scalars(select(Outbox).where(Outbox.task_id == task_id))) == []
    assert github.writes == []


def test_completed_review_reuse_completes_new_task_without_completion_side_effects(case):
    app, client, github, original_id, action_id = case
    processor = app.state.processor
    events, finalizers, notifications = [], [], []

    async def event_sink(event, task_id, data):
        events.append((event, task_id))

    async def finalizer(task_id):
        finalizers.append(task_id)

    async def notify(task_id, kind, subject, body):
        notifications.append((task_id, kind))

    async def verdict(*args, **kwargs):
        return ReviewVerdict(verdict="approved", summary=PAYLOAD["body"], risk="low")

    processor.event_sink = event_sink
    processor.plugins.finalize_task = finalizer
    processor.notify = notify
    processor.structured_agent = verdict
    with app.state.sessions.begin() as db:
        db.delete(db.get(Outbox, action_id))
        db.get(Task, original_id).status = "queued"

    async def run_original():
        await processor.process(original_id)
        await asyncio.sleep(0)

    client.portal.call(run_original)
    assert github.writes == [PAYLOAD]
    assert events.count(("pr.reviewed", original_id)) == 1
    assert finalizers == [original_id]
    assert notifications == [(original_id, "report")]
    with app.state.sessions() as db:
        published_action_id = db.scalar(select(Outbox.id).where(Outbox.task_id == original_id))

    reused_id = webhook_task(case, "second-completed-review")

    async def run_reused():
        await processor.process(reused_id)
        await asyncio.sleep(0)

    client.portal.call(run_reused)
    with app.state.sessions() as db:
        assert db.get(Task, original_id).status == "reviewed"
        second = db.get(Task, reused_id)
        assert second.status == "reviewed"
        assert second.data["review_url"].endswith("-42")
        assert second.data["review_reused_from"]["action_id"] == published_action_id
        assert db.scalar(select(Timeline).where(Timeline.task_id == reused_id,
            Timeline.kind == "review_completion_side_effects_skipped"))
        assert len(list(db.scalars(select(Outbox).where(Outbox.kind == "pr_review")))) == 1
    assert github.writes == [PAYLOAD]
    assert events.count(("pr.reviewed", reused_id)) == 0
    assert events.count(("pr.reviewed", original_id)) == 1
    assert finalizers == [original_id]
    assert notifications == [(original_id, "report")]


@pytest.mark.parametrize("marker_head,marker_attempt", [(HEAD, 1), ("b" * 40, 2)])
def test_old_reuse_marker_does_not_suppress_independent_completion(case, marker_head, marker_attempt):
    app, client, _, task_id, _ = case
    events = []

    async def event_sink(event, event_task_id, data):
        events.append((event, event_task_id))

    app.state.processor.event_sink = event_sink
    with app.state.sessions.begin() as db:
        task = db.get(Task, task_id)
        task.attempts = 2
        task.data = {**task.data, "review_reused_from": {
            "action_id": "previous-action", "head_sha": marker_head, "attempt": marker_attempt}}

    async def complete():
        app.state.processor.change_status(task_id, "reviewed", head_sha=HEAD)
        await asyncio.sleep(0)

    client.portal.call(complete)
    assert events == [("pr.reviewed", task_id)]


def test_reconciles_existing_review_without_post(case):
    case[2].rows = [case[2].published()]
    result = recover(case, preview(case))
    assert result.status_code == 200 and result.json()["outcome"] == "reconciled"
    assert state(case) == ("queued", "completed", 1)
    assert write(case)["html_url"].endswith("-42")
    assert case[2].writes == []


def test_reconciled_review_completes_real_task_without_another_post(case):
    original_verdict(case)
    no_second_verdict(case)
    case[2].rows = [case[2].published()]
    assert recover(case, preview(case)).status_code == 200
    case[1].portal.call(case[0].state.processor.process, case[3])
    assert state(case) == ("reviewed", "completed", 1)
    assert case[2].writes == []
    with case[0].state.sessions() as db:
        task = db.get(Task, case[3])
        assert task.data["review_url"].endswith("-42")
        assert db.scalar(select(Timeline).where(Timeline.task_id == case[3], Timeline.kind == "pr_review_resumed"))


def test_reconciled_changes_request_restores_findings_and_waiting_state(case):
    app, client, github, task_id, action_id = case
    summary = "Multiplication still has a blocking defect."
    body = summary + "\n\n[blocking] src/calculator.js: multiply returns addition"
    request = {**PAYLOAD, "event": "REQUEST_CHANGES", "body": body}
    with app.state.sessions.begin() as db:
        action = db.get(Outbox, action_id)
        action.action_key = f"pr-review:owner/repo:5:{HEAD}:REQUEST_CHANGES"
        action.data = {"head_sha": HEAD, "event": "REQUEST_CHANGES", "review_request": request}
        db.add(Timeline(task_id=task_id, kind="pr_review_completed", timestamp=action.created - 1,
            data={"head_sha": HEAD, "verdict": "changes_required", "risk": "medium", "summary": summary,
                  "blocking_issues": [{"severity": "blocking", "path": "src/calculator.js",
                                       "message": "multiply returns addition", "issue_type": "logic"}], "suggestions": []}))
    github.rows = [github.published(state="CHANGES_REQUESTED", body=body)]
    no_second_verdict(case)
    assert recover(case, preview(case, request)).status_code == 200
    client.portal.call(app.state.processor.process, task_id)
    assert state(case) == ("waiting_for_contributor", "completed", 1)
    assert github.writes == []
    with app.state.sessions() as db:
        finding = db.scalar(select(ReviewFinding).where(ReviewFinding.task_id == task_id))
        assert finding.data["message"] == "multiply returns addition"


def test_reconciled_review_rejects_different_event_for_same_task_and_head(case):
    case[2].rows = [case[2].published()]
    assert recover(case, preview(case)).status_code == 200
    other = {**PAYLOAD, "event": "COMMENT", "body": "A new model verdict"}
    with pytest.raises(RecoveryConflict):
        case[1].portal.call(case[0].state.processor.github_action, case[3], "pr_review",
            f"pr-review:owner/repo:5:{HEAD}:COMMENT",
            {"head_sha": HEAD, "event": "COMMENT", "review_request": other}, case[2].publish)
    assert case[2].writes == []


def test_reconciled_review_waits_if_current_policy_now_requires_owner(case):
    original_verdict(case)
    no_second_verdict(case)
    case[2].rows = [case[2].published()]
    assert recover(case, preview(case)).status_code == 200
    case[2].title = "Add new feature to calculator API"
    case[1].portal.call(case[0].state.processor.process, case[3])
    assert state(case) == ("waiting_for_owner", "completed", 1)
    assert case[2].writes == []


def test_completed_review_does_not_block_a_new_pr_head(case):
    app, client, github, task_id, _ = case
    github.rows = [github.published()]
    assert recover(case, preview(case)).status_code == 200
    new_head = "b" * 40
    async def next_write():
        return {"id": 43, "html_url": "https://github.com/owner/repo/pull/5#pullrequestreview-43"}
    data = {"head_sha": new_head, "event": "APPROVE", "review_request":
            {"commit_id": new_head, "event": "APPROVE", "body": "New head reviewed", "comments": []}}
    result = client.portal.call(app.state.processor.github_action, task_id, "pr_review",
        f"pr-review:owner/repo:5:{new_head}", data, next_write)
    assert result["id"] == 43


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


def test_authorized_retry_uses_original_request_in_real_task(case):
    original_verdict(case)
    no_second_verdict(case)
    assert recover(case, {**preview(case), "retry_authorized": True}).status_code == 200
    case[1].portal.call(case[0].state.processor.process, case[3])
    assert state(case) == ("reviewed", "completed", 2)
    assert case[2].writes == [PAYLOAD]
    case[1].portal.call(case[0].state.processor.process, case[3])
    assert case[2].writes == [PAYLOAD]


def test_cancelled_review_post_becomes_unknown_and_can_reconcile_online(case):
    app, client, github, task_id, action_id = case
    original_verdict(case)
    with app.state.sessions.begin() as db:
        db.get(Task, task_id).status = "queued"
        action = db.get(Outbox, action_id)
        action.status, action.attempts = "pending", 0
    async def verdict(*args, **kwargs):
        return ReviewVerdict(verdict="approved", summary=PAYLOAD["body"], risk="low")
    app.state.processor.structured_agent = verdict

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def pause():
            entered.set()
            await release.wait()
        github.review_pause = pause
        run = asyncio.create_task(app.state.processor.process(task_id))
        await entered.wait()
        assert state(case) == ("running", "executing", 1)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
    client.portal.call(scenario)
    assert state(case) == ("interrupted", "unknown", 1)
    assert client.post(f"/api/tasks/{task_id}/retry").status_code == 409
    github.review_pause = None
    github.rows = [github.published()]
    assert recover(case, preview(case)).status_code == 200
    no_second_verdict(case)
    client.portal.call(app.state.processor.process, task_id)
    assert state(case) == ("reviewed", "completed", 1)
    assert github.writes == []


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
    with case[0].state.sessions() as db:
        task = db.get(Task, case[3])
        assert task.data["review_request_sha256"] == payload_hash(PAYLOAD)
        assert task.data["review_event"] == "APPROVE"


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
