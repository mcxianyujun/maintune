import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from sqlalchemy import select

from maintainer.db import Config, Outbox, Repository, ReviewFinding, Task, Timeline, WebhookDelivery
from maintainer.github import GitHubAppClient, GitHubError, decode_github_content, ingest_webhook, verify_signature
from maintainer.notifications import EmailNotifier
from maintainer.runtime import RuntimeResult, parse_structured, sandbox_observation_type, structured_call
from maintainer.sandboxes import ShipyardSandbox
from maintainer.schemas import IssueAnalysis, ReviewVerdict
from maintainer.tasks import TaskProcessor
from test_foundation import app, client


def signed(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def repository(db, name="owner/repo", **changes):
    data = {"enabled": True, "auto_handle_issues": True, "auto_review_prs": True, "auto_merge": False, "default_branch": "main", "install_command": "", "test_command": "", "lint_command": "", "build_command": "", "working_directory": ".", "additional_instructions": ""}
    data.update(changes)
    row = Repository(full_name=name, installation_id=7, data=data)
    db.add(row)
    return row


def payload(kind="issues", action="opened", number=3):
    field = "pull_request" if kind == "pull_request" else "issue"
    return {"action": action, "repository": {"full_name": "owner/repo"}, field: {"number": number}, "installation": {"id": 7}, "sender": {"login": "alice"}}


def test_signature_validation():
    body = b'{"ok":true}'
    assert verify_signature(body, signed("secret", body), "secret")
    assert not verify_signature(body + b"x", signed("secret", body), "secret")
    assert not verify_signature(body, None, "secret")


def test_webhook_duplicate_and_routing(app):
    body = json.dumps(payload()).encode()
    with app.state.sessions.begin() as db:
        repository(db)
        first, task, duplicate = ingest_webhook(db, "delivery-1", "issues", body, payload())
        assert task.kind == "issue" and not duplicate
    with app.state.sessions.begin() as db:
        second, same, duplicate = ingest_webhook(db, "delivery-1", "issues", body, payload())
        assert duplicate and same.id == task.id
        assert len(list(db.scalars(select(Task)))) == 1
    with app.state.sessions.begin() as db:
        _, pr, _ = ingest_webhook(db, "delivery-2", "pull_request", json.dumps(payload("pull_request")).encode(), payload("pull_request"))
        assert pr.kind == "pull_request"


def test_waiting_issue_comment_resumes_existing_task(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=3, event="issues.opened", delivery_id="old", status="waiting_for_contributor", data={})
        db.add(task); db.flush(); task_id = task.id
    data = payload("issue_comment", "created")
    body = json.dumps(data).encode()
    with app.state.sessions.begin() as db:
        _, resumed, _ = ingest_webhook(db, "comment-delivery", "issue_comment", body, data)
        assert resumed.id == task_id and resumed.status == "queued" and resumed.delivery_id == "old"
        assert len(list(db.scalars(select(Task)))) == 1
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "contributor_reply_received"))


@pytest.mark.parametrize(("title", "expected_event"), [
    ("Add automatic stale issue cleanup after 30 days", "product_decision_required"),
    ("Change webhook signature validation", "high_risk_owner_gate"),
])
def test_issue_deterministic_owner_gate_prevents_worker_and_sandbox(app, title, expected_event):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=20, event="issues.opened", delivery_id=title, status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        async def issue_context(self, *args): return {"issue": {"title": title, "body": "Please implement this."}, "comments": []}
        async def repository_guidance(self, *args): return "guidance"

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def analysis(*args):
        return IssueAnalysis(status="actionable", summary="A product change", reason="clear", risk="low", suggested_plan=["Option A", "Option B"])
    processor.structured_agent = analysis
    processor.sandbox = lambda: (_ for _ in ()).throw(AssertionError("sandbox must not be created"))
    asyncio.run(processor.process_issue(task_id, GitHub(), 7, "owner/repo", 20, {"default_branch": "main", "additional_instructions": ""}))
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "waiting_for_owner" and task.data["owner_gate"] == expected_event
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == expected_event))
        assert not db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "sandbox_created"))


def test_non_actionable_issue_uses_lightweight_mark_only_triage(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=21, event="issues.opened", delivery_id="chat", status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        async def issue_context(self, *args): return {"issue": {"title": "洛天依好可爱 😋", "body": ""}, "comments": []}
        async def repository_guidance(self, *args): return "guidance"

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def unexpected(*args): raise AssertionError("non-actionable issue must not call a model")
    processor.structured_agent = unexpected
    asyncio.run(processor.process_issue(task_id, GitHub(), 7, "owner/repo", 21, {"default_branch": "main", "additional_instructions": ""}))
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "non_actionable" and task.data["triage"]["classification"] == "non_actionable"
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "non_actionable")).data["action"] == "mark_only"


def test_non_actionable_issue_title_does_not_force_model_work(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=43, event="issues.opened", delivery_id="chat-title", status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        async def issue_context(self, *args): return {"issue": {"title": "A4 Chat: 洛天依好可爱", "body": "洛天依好可爱 😋"}, "comments": []}
        async def repository_guidance(self, *args): return "guidance"

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def unexpected(*args): raise AssertionError("non-actionable issue must not call a model")
    processor.structured_agent = unexpected
    asyncio.run(processor.process_issue(task_id, GitHub(), 7, "owner/repo", 43, {"default_branch": "main", "additional_instructions": ""}))
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "non_actionable"
        assert not db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "agent_call"))


def test_bot_clarification_comment_does_not_resume_waiting_contributor(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=44, event="issues.opened", delivery_id="waiting-comment", status="waiting_for_contributor", data={})
        db.add(task); db.flush()
        delivery, resumed, duplicate = ingest_webhook(db, "bot-comment-delivery", "issue_comment", b"{}", {
            "action": "created", "repository": {"full_name": "owner/repo"}, "issue": {"number": 44},
            "comment": {"id": 1, "user": {"login": "maintainer[bot]", "type": "Bot"}}, "sender": {"type": "Bot"},
        })
        assert resumed is None and not duplicate and delivery.status == "ignored_bot_comment"
        assert db.get(Task, task.id).status == "waiting_for_contributor"


def test_incomplete_issue_requests_clarification_then_resumes_same_task(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=22, event="issues.opened", delivery_id="incomplete", status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        comments = []
        replies = []
        async def issue_context(self, *args): return {"issue": {"title": "Sandbox 不工作了", "body": ""}, "comments": self.comments}
        async def repository_guidance(self, *args): return "guidance"
        async def comment(self, *args): self.replies.append(args[-1]); return {"id": 1, "html_url": "https://example/comment"}

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    answers = [
        IssueAnalysis(status="need_information", summary="Need reproduction details", reason="missing", risk="low", requested_information=["Local or Shipyard Neo?", "What error is shown?", "Steps to reproduce?"]),
        IssueAnalysis(status="actionable", summary="Reproducible Local sandbox failure", reason="complete", risk="low", suggested_plan=["Fix it"]),
    ]
    async def structured(*args): return answers.pop(0)
    proceeded = []
    async def fixed(*args): proceeded.append(True)
    processor.structured_agent = structured
    processor.fix_issue = fixed
    github = GitHub()
    asyncio.run(processor.process_issue(task_id, github, 7, "owner/repo", 22, {"default_branch": "main", "additional_instructions": ""}))
    with app.state.sessions.begin() as db:
        assert db.get(Task, task_id).status == "waiting_for_contributor"
        db.get(Task, task_id).status = "running"
    github.comments = [{"user": {"login": "alice"}, "body": "Local sandbox, version 0.1, error: permission denied. Reproduce by running npm test."}]
    asyncio.run(processor.process_issue(task_id, github, 7, "owner/repo", 22, {"default_branch": "main", "additional_instructions": ""}))
    assert proceeded == [True] and len(github.replies) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "clarification_resolved"))


def test_webhook_endpoint_auth_and_duplicate(client, app):
    secret = "webhook-secret"
    with app.state.sessions.begin() as db:
        db.add(Config(id="github", data={"app_id": 1, "webhook_secret": app.state.vault.encrypt(secret)}))
        repository(db)
    body = json.dumps(payload()).encode()
    headers = {"X-GitHub-Delivery": "endpoint-delivery", "X-GitHub-Event": "issues", "X-Hub-Signature-256": signed(secret, body)}
    assert client.post("/webhooks/github", content=body, headers={**headers, "X-Hub-Signature-256": "sha256=bad"}).status_code == 401
    first = client.post("/webhooks/github", content=body, headers=headers)
    assert first.status_code == 202 and first.json()["task_id"]
    assert client.post("/webhooks/github", content=body, headers=headers).json()["duplicate"]


def test_installation_token_cache_and_error(monkeypatch):
    private = jwt.algorithms.RSAAlgorithm.generate_private_key() if hasattr(jwt.algorithms.RSAAlgorithm, "generate_private_key") else None
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = private or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"token": "ghs_new_format_token", "expires_at": "unused"})
    client = GitHubAppClient(42, pem)
    monkeypatch.setattr(client, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com/"))
    one = asyncio.run(client.installation_token(7)); two = asyncio.run(client.installation_token(7))
    assert one == two == "ghs_new_format_token" and len(calls) == 1
    assert jwt.decode(calls[0].headers["Authorization"].removeprefix("Bearer "), key.public_key(), algorithms=["RS256"], options={"verify_aud": False})["iss"] == "42"
    monkeypatch.setattr(client, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)), base_url="https://api.github.com/"))
    with pytest.raises(GitHubError): asyncio.run(client.installation_token(8))


def test_github_content_decoder_accepts_mime_wrapping_and_rejects_invalid_data():
    assert decode_github_content("aGVs\nbG8=\n") == b"hello"
    with pytest.raises(GitHubError):
        decode_github_content("not base64!")


def test_repository_guidance_decodes_github_multiline_base64(monkeypatch):
    client = GitHubAppClient(1, "unused")
    encoded = "IyBUZXN0\nXG5ndWlkZQ==\n"
    async def request(*args, **kwargs):
        path = args[2]
        if path.endswith("README.md"):
            return {"encoding": "base64", "size": 13, "content": encoded}
        raise GitHubError("missing")
    monkeypatch.setattr(client, "request", request)
    assert "# Test" in asyncio.run(client.repository_guidance(7, "owner/repo", "main"))


class Completion:
    def __init__(self, text): self.text=text; self.input_tokens=1; self.output_tokens=2; self.total_tokens=3; self.usage_reported=True


def test_structured_output_and_retry_limit():
    valid = '{"status":"actionable","summary":"s","reason":"r","risk":"low","requested_information":[],"suggested_plan":[]}'
    assert parse_structured(valid, IssueAnalysis).status == "actionable"
    class Provider:
        def __init__(self): self.calls=0
        async def complete(self, *args):
            self.calls += 1
            return Completion("invalid" if self.calls == 1 else valid)
    provider = Provider()
    result, completions = asyncio.run(structured_call(provider, "m", "s", "p", IssueAnalysis, 1, retries=1))
    assert result.status == "actionable" and len(completions) == 2
    with pytest.raises(ValueError): asyncio.run(structured_call(Provider(), "m", "s", "p", ReviewVerdict, 1, retries=0))


def test_openhands_custom_observation_round_trips_through_event_schema():
    from openhands.sdk.event.llm_convertible.observation import ObservationEvent

    observation = sandbox_observation_type().from_text("tool output")
    event = ObservationEvent(tool_name="maintainer_read", tool_call_id="call-1", observation=observation, action_id="action-1")
    restored = ObservationEvent.model_validate_json(event.model_dump_json())
    assert restored.observation.text == "tool output"
    assert restored.observation.kind == "MaintainerSandboxObservation"


def test_diff_line_mapping_and_policy_outbox(app):
    assert TaskProcessor.diff_lines("@@ -1,2 +1,3 @@\n old\n+new\n unchanged") == {1, 2, 3}
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="x", data={})
        db.add(task); db.flush(); task_id=task.id
    calls=[]
    async def perform(): calls.append(1); return {"id": 9, "html_url": "https://example/9"}
    first=asyncio.run(processor.github_action(task_id,"comment","unique",{},perform))
    second=asyncio.run(processor.github_action(task_id,"comment","unique",{},perform))
    assert first["id"] == 9 and second["id"] == "9" and len(calls)==1


def test_failed_status_records_sanitized_failure_event(app):
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    with app.state.sessions.begin() as db:
        task = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="failure-event", status="running", attempts=2, data={})
        db.add(task); db.flush(); task_id = task.id
    processor.change_status(task_id, "failed_tests", failure_stage="tests", exception_type="TestFailure", summary="assertion failed")
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        event = db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "task_failed"))
        assert task.data["failure"] == event.data
        assert event.data == {"stage": "tests", "exception_type": "TestFailure", "message": "assertion failed", "attempt": 2, "retry": 1}


def test_failed_task_retry_is_audited_and_rejects_non_failure(client, app):
    with app.state.sessions.begin() as db:
        failed = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="retry-failed", status="failed_environment", attempts=1, data={"error":"safe", "failure":{"stage":"x"}})
        running = Task(kind="issue", repository="owner/repo", number=2, event="issues.opened", delivery_id="retry-running", status="running", data={})
        bot = Task(kind="pull_request", repository="owner/repo", number=3, event="pull_request.opened", delivery_id="recheck-bot", status="bot_skipped", attempts=1, data={})
        external = Task(kind="pull_request", repository="owner/repo", number=4, event="pull_request.synchronize", delivery_id="recheck-external", status="waiting_for_owner", attempts=1, data={})
        db.add_all([failed, running, bot, external]); db.flush(); failed_id, running_id, bot_id, external_id = failed.id, running.id, bot.id, external.id
    assert client.post(f"/api/tasks/{failed_id}/retry").json() == {"status": "queued"}
    assert client.post(f"/api/tasks/{running_id}/retry").status_code == 409
    assert client.post(f"/api/tasks/{bot_id}/recheck").json() == {"status": "queued"}
    assert client.post(f"/api/tasks/{external_id}/recheck").json() == {"status": "queued"}
    with app.state.sessions() as db:
        task = db.get(Task, failed_id)
        assert task.status == "queued" and "failure" not in task.data and "error" not in task.data
        assert db.scalar(select(Timeline).where(Timeline.task_id == failed_id, Timeline.kind == "task_retried"))
        assert db.get(Task, bot_id).status == "queued"
        assert db.get(Task, external_id).status == "queued"
        assert db.scalar(select(Timeline).where(Timeline.task_id == bot_id, Timeline.kind == "task_rechecked"))


def test_restart_marks_tasks_and_actions_unknown(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task=Task(kind="issue",repository="owner/repo",number=1,event="issues.opened",delivery_id="restart",status="running",data={})
        db.add(task);db.flush()
        db.add(Outbox(task_id=task.id, action_key="restart-action", kind="comment", status="executing", data={}))
    from fastapi.testclient import TestClient
    with TestClient(app): pass
    with app.state.sessions() as db:
        assert db.scalar(select(Task).where(Task.delivery_id=="restart")).status == "interrupted"
        assert db.scalar(select(Outbox).where(Outbox.action_key=="restart-action")).status == "unknown"


def test_shipyard_lifecycle_and_failure(monkeypatch):
    seen=[]
    shell_payloads=[]
    def handler(request):
        seen.append((request.method,request.url.path))
        if request.method=="POST" and request.url.path=="/v1/sandboxes": return httpx.Response(201,json={"id":"sbx"})
        if request.url.path.endswith("/shell/exec"):
            shell_payloads.append(request.read())
            return httpx.Response(200,json={"exit_code":0,"output":"ok","execution_id":"e"})
        if request.method=="PUT": return httpx.Response(200,json={"status":"ok"})
        if request.method=="GET": return httpx.Response(200,json={"content":"hello"})
        if request.method=="DELETE": return httpx.Response(204)
        return httpx.Response(500)
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))
    sandbox=ShipyardSandbox("https://bay.example","key")
    sid=asyncio.run(sandbox.create("task")); asyncio.run(sandbox.write_file(sid,"a.txt","hello"))
    assert asyncio.run(sandbox.read_file(sid,"a.txt"))=="hello"
    assert asyncio.run(sandbox.exec(sid,"echo ok",3))["exit_code"]==0
    assert asyncio.run(sandbox.exec(sid,"echo ok",600))["exit_code"]==0
    assert json.loads(shell_payloads[-1])["timeout"] == 300
    asyncio.run(sandbox.destroy(sid))
    assert seen[0] == ("POST","/v1/sandboxes") and seen[-1] == ("DELETE","/v1/sandboxes/sbx")
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(503)),**kwargs))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(sandbox.create("failed-task"))


def test_email_success_and_failure(monkeypatch):
    sent=[]
    class SMTP:
        def __init__(self,*a,**k): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def starttls(self,context): sent.append("tls")
        def login(self,u,p): sent.append((u,p))
        def send_message(self,m): sent.append(m["X-AI-Maintainer-Idempotency-Key"])
    monkeypatch.setattr("smtplib.SMTP",SMTP)
    settings={"host":"smtp.example","port":587,"username":"u","from_address":"a@example.com","owner_email":"b@example.com","mode":"starttls"}
    EmailNotifier(settings,"p")._send("subject","body","key")
    assert sent == ["tls",("u","p"),"key"]
    class Broken(SMTP):
        def send_message(self,m): raise OSError("down")
    monkeypatch.setattr("smtplib.SMTP",Broken)
    with pytest.raises(OSError): EmailNotifier(settings,"p")._send("s","b","k")


@pytest.mark.parametrize(("verdict", "expected_event", "expected_status"), [
    ({"verdict":"changes_required","blocking_issues":[{"severity":"blocking","path":"a.py","line":2,"message":"Incorrect result","issue_type":"correctness"}],"suggestions":[],"summary":"fix it","risk":"medium"}, "REQUEST_CHANGES", "waiting_for_contributor"),
    ({"verdict":"approved","blocking_issues":[],"suggestions":[{"severity":"suggestion","path":"a.py","line":2,"message":"Optional rename","issue_type":"style"}],"summary":"safe","risk":"low"}, "APPROVE", "reviewed"),
    ({"verdict":"approved","blocking_issues":[],"suggestions":[],"summary":"safe","risk":"low"}, "APPROVE", "reviewed"),
])
def test_pull_review_events(app, verdict, expected_event, expected_status):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="pull_request", repository="owner/repo", number=8, event="pull_request.opened", delivery_id="review-" + expected_event, data={})
        db.add(task); db.flush(); task_id = task.id
    class GitHub:
        events=[]
        async def repository_guidance(self, *args): return "instructions"
        async def pull_context(self, *args):
            return {"pull":{"title":"change","body":"body","draft":False,"user":{"login":"alice","type":"User"},"head":{"sha":"abc"}},"files":[{"filename":"a.py","patch":"@@ -1 +1,2 @@\n old\n+new"}],"commits":[{}],"checks":{"check_runs":[]},"statuses":{"state":"success"}}
        async def review(self, installation, repo, number, sha, event, body, comments):
            self.events.append((event, comments)); return {"id":1,"html_url":"https://example/review"}
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def structured(*args): return ReviewVerdict.model_validate(verdict)
    processor.structured_agent = structured
    github=GitHub(); asyncio.run(processor.process_pull(task_id, github, 7, "owner/repo", 8, {}))
    with app.state.sessions() as db: assert db.get(Task, task_id).status == expected_status
    assert github.events[-1][0] == expected_event


def test_pull_context_uses_previous_head_diff_when_aggregate_diff_is_empty():
    class GitHub(GitHubAppClient):
        def __init__(self): self.calls = []
        async def request(self, installation_id, method, path, **kwargs):
            self.calls.append(path)
            if path == "repos/owner/repo/pulls/3":
                return {"head": {"sha": "fixed"}}
            if path.endswith("/files"):
                return []
            if path.endswith("/commits"):
                return [{"sha": "bad"}, {"sha": "fixed"}]
            if path.endswith("/check-runs"):
                return {"check_runs": []}
            if path.endswith("/status"):
                return {"state": "pending", "statuses": []}
            if path.endswith("/compare/bad...fixed"):
                return {"files": [{"filename": "src/calculator.js", "patch": "@@ -8 +8 @@\n-return a + b;\n+return a * b;"}]}
            raise AssertionError(path)
    github = GitHub()
    context = asyncio.run(github.pull_context(7, "owner/repo", 3, "bad"))
    assert context["diff_source"] == "head_comparison"
    assert context["files"][0]["filename"] == "src/calculator.js"
    assert context["diff_size"] > 0
    assert "repos/owner/repo/compare/bad...fixed" in github.calls


def test_missing_github_diff_fails_environment_before_reviewer(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="pull_request", repository="owner/repo", number=3, event="pull_request.synchronize", delivery_id="missing-diff", status="queued", data={})
        db.add(task); db.flush(); task_id = task.id
    class GitHub:
        async def pull_context(self, *args):
            raise GitHubError("GitHub returned commits but no reviewable pull request diff")
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    processor.app_client = lambda: GitHub()
    reviewer_called = False
    async def structured(*args):
        nonlocal reviewer_called
        reviewer_called = True
    processor.structured_agent = structured
    asyncio.run(processor.process(task_id))
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        failure = db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "task_failed"))
        assert task.status == "failed_environment"
        assert failure.data["stage"] == "github_pull_context" and failure.data["exception_type"] == "GitHubError"
    assert reviewer_called is False


def test_synchronize_reloads_latest_diff_resolves_old_finding_and_approves(app):
    with app.state.sessions.begin() as db:
        repository(db)
        opened = Task(kind="pull_request", repository="owner/repo", number=3, event="pull_request.opened", delivery_id="external-opened", status="running", data={})
        db.add(opened); db.flush(); opened_id, opened_created = opened.id, opened.created

    bad_file = {"filename": "src/calculator.js", "patch": "@@ -8 +8 @@\n-return a * b;\n+return a + b;", "status": "modified", "additions": 1, "deletions": 1}
    fixed_file = {"filename": "src/calculator.js", "patch": "@@ -8 +8 @@\n-return a + b;\n+return a * b;", "status": "modified", "additions": 1, "deletions": 1}
    contexts = [
        {"pull":{"title":"Improve multiply implementation","body":"Natural description","draft":False,"user":{"login":"alice","type":"User"},"head":{"sha":"bad"},"base":{"ref":"main"}},"files":[bad_file],"aggregate_files":[bad_file],"latest_files":[],"diff_source":"pull","diff_size":len(bad_file["patch"]),"commits":[{"sha":"bad"}],"checks":{"check_runs":[]},"statuses":{"state":"pending","statuses":[]}},
        {"pull":{"title":"Improve multiply implementation","body":"Natural description","draft":False,"user":{"login":"alice","type":"User"},"head":{"sha":"fixed"},"base":{"ref":"main"}},"files":[fixed_file],"aggregate_files":[],"latest_files":[fixed_file],"diff_source":"head_comparison","diff_size":len(fixed_file["patch"]),"commits":[{"sha":"bad"},{"sha":"fixed"}],"checks":{"check_runs":[]},"statuses":{"state":"pending","statuses":[]}},
    ]
    class GitHub:
        previous_heads = []
        reviews = []
        async def repository_guidance(self, *args): return "instructions"
        async def pull_context(self, installation, repo, number, previous_head=""):
            self.previous_heads.append(previous_head)
            return contexts.pop(0)
        async def review(self, installation, repo, number, sha, event, body, comments):
            self.reviews.append((sha, event, body, comments))
            return {"id": len(self.reviews), "html_url": f"https://example/review/{len(self.reviews)}"}
    verdicts = [
        ReviewVerdict(verdict="changes_required", blocking_issues=[{"severity":"blocking","path":"src/calculator.js","line":8,"message":"multiply performs addition","issue_type":"correctness"}], summary="multiply is incorrect", risk="medium"),
        ReviewVerdict(verdict="approved", blocking_issues=[], suggestions=[{"severity":"suggestion","path":"src/calculator.js","line":10,"message":"Optional extra edge-case coverage","issue_type":"test-coverage"}], summary="The previous multiply finding is resolved.", risk="low"),
    ]
    prompts = []
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def structured(task_id, agent, prompt, schema):
        prompts.append(prompt)
        return verdicts.pop(0)
    processor.structured_agent = structured
    github = GitHub()
    asyncio.run(processor.process_pull(opened_id, github, 7, "owner/repo", 3, {}))

    with app.state.sessions.begin() as db:
        sync = Task(kind="pull_request", repository="owner/repo", number=3, event="pull_request.synchronize", delivery_id="external-sync", status="running", created=opened_created + 1, data={})
        db.add(sync); db.flush(); sync_id = sync.id
    asyncio.run(processor.process_pull(sync_id, github, 7, "owner/repo", 3, {}))

    assert github.previous_heads == ["", "bad"]
    assert [item[1] for item in github.reviews] == ["REQUEST_CHANGES", "APPROVE"]
    assert github.reviews[1][3] == [] and "Optional extra edge-case coverage" in github.reviews[1][2]
    assert "multiply performs addition" in prompts[1]
    assert "return a * b" in prompts[1]
    with app.state.sessions() as db:
        assert db.get(Task, opened_id).status == "waiting_for_contributor"
        sync = db.get(Task, sync_id)
        assert sync.status == "reviewed" and sync.data["review_event"] == "APPROVE" and sync.data["head_sha"] == "fixed"
        finding = db.scalar(select(ReviewFinding).where(ReviewFinding.repository == "owner/repo", ReviewFinding.number == 3))
        assert finding.data["resolved"] is True and finding.data["resolved_head_sha"] == "fixed"
        loaded = db.scalar(select(Timeline).where(Timeline.task_id == sync_id, Timeline.kind == "pr_context_loaded"))
        assert loaded.data["file_count"] == 1 and loaded.data["diff_source"] == "head_comparison" and loaded.data["previous_blocking_count"] == 1
        assert db.scalar(select(Timeline).where(Timeline.task_id == sync_id, Timeline.kind == "review_findings_resolved"))


def test_review_fingerprint_saved_only_after_success(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="pull_request", repository="owner/repo", number=9, event="pull_request.opened", delivery_id="review-failure", data={})
        db.add(task); db.flush(); task_id=task.id
    class GitHub:
        async def repository_guidance(self, *args): return "instructions"
        async def pull_context(self,*args): return {"pull":{"title":"x","draft":False,"user":{"type":"User"},"head":{"sha":"abc"}},"files":[{"filename":"a.py","patch":"@@ -1 +1 @@\n+bad"}],"commits":[{}],"checks":{"check_runs":[]},"statuses":{"state":"success"}}
        async def review(self,*args): raise RuntimeError("timeout")
    p=TaskProcessor(app.state.sessions,app.state.vault,app.state.settings)
    finding={"severity":"blocking","path":"a.py","line":1,"message":"Bug","issue_type":"correctness"}
    async def structured(*args): return ReviewVerdict(verdict="changes_required",blocking_issues=[finding],summary="bad",risk="high")
    p.structured_agent=structured
    with pytest.raises(RuntimeError): asyncio.run(p.process_pull(task_id,GitHub(),7,"owner/repo",9,{}))
    from maintainer.db import ReviewFinding
    with app.state.sessions() as db: assert list(db.scalars(select(ReviewFinding))) == []


@pytest.mark.parametrize(("auto_merge", "check_runs", "test_exit", "expected_status", "merge_calls", "expected_reason"), [
    (False, [], 0, "bot_merge_deferred", 0, "automatic merge disabled"),
    (True, [], 0, "bot_merged", 1, None),
    (True, [{"status": "completed", "conclusion": "failure"}], 0, "bot_merge_deferred", 0, "CI not passed"),
    (True, [], 1, "bot_merge_deferred", 0, "origin task tests did not pass"),
])
def test_bot_pull_uses_deterministic_origin_policy_without_pr_reviewer(app, auto_merge, check_runs, test_exit, expected_status, merge_calls, expected_reason):
    with app.state.sessions.begin() as db:
        repository(db, auto_merge=auto_merge)
        origin = Task(kind="issue", repository="owner/repo", number=10, event="issues.opened", delivery_id=f"origin-{auto_merge}", status="pr_created", attempts=1, data={})
        db.add(origin); db.flush()
        pull_url = "https://github.com/owner/repo/pull/12"
        origin.data = {"pull_number": 12, "pull_url": pull_url, "summary": "approved"}
        db.add(Timeline(task_id=origin.id, kind="tests_completed", data={"exit_code": test_exit, "attempt": 1}))
        db.add(Timeline(task_id=origin.id, kind="agent_call", data={"agent": "code_reviewer", "model": "m"}))
        db.add(Outbox(task_id=origin.id, kind="fix_pr", action_key=f"fix-pr:{origin.id}", status="completed", data={"paths": ["src/a.js"], "base_sha": "base"}, external_id="123", external_url=pull_url))
        pull_task = Task(kind="pull_request", repository="owner/repo", number=12, event="pull_request.opened", delivery_id=f"pull-{auto_merge}", status="running", attempts=1, data={})
        db.add(pull_task); db.flush(); origin_id, pull_task_id = origin.id, pull_task.id

    class GitHub:
        merges = 0
        async def pull_context(self, *args):
            return {
                "pull": {"body": f"<!-- ai-maintainer:{origin_id}:fix-pr -->", "html_url": pull_url, "head": {"ref": f"ai-maintainer/fix-10-{origin_id[:8]}", "sha": "head", "repo": {"full_name": "owner/repo"}}},
                "commits": [{"sha": "head", "parents": [{"sha": "base"}]}],
                "checks": {"check_runs": check_runs}, "statuses": {"state": "pending", "statuses": []}, "files": [],
            }
        async def merge_pull_request(self, *args):
            self.merges += 1
            return {"merged": True, "sha": "merge"}

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def unexpected_reviewer(*args):
        raise AssertionError("pr_reviewer must not run for Maintainer PRs")
    processor.structured_agent = unexpected_reviewer
    github = GitHub()
    asyncio.run(processor.process_pull(pull_task_id, github, 7, "owner/repo", 12, {"auto_merge": auto_merge}))
    assert github.merges == merge_calls
    with app.state.sessions() as db:
        pull_task = db.get(Task, pull_task_id)
        origin = db.get(Task, origin_id)
        assert pull_task.status == expected_status
        if expected_status == "bot_merged":
            assert origin.status == "merged" and origin.data["merge_sha"] == "merge"
            assert db.scalar(select(Timeline).where(Timeline.task_id == pull_task_id, Timeline.kind == "auto_merge_approved"))
        else:
            assert origin.status == "pr_created"
            event = db.scalar(select(Timeline).where(Timeline.task_id == pull_task_id, Timeline.kind == "auto_merge_deferred"))
            assert expected_reason in event.data["reasons"]


def test_worker_reviewer_loop_is_bounded(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task=Task(kind="issue",repository="owner/repo",number=10,event="issues.opened",delivery_id="loop",attempts=2,data={})
        db.add(task);db.flush();task_id=task.id
    class Sandbox:
        def __init__(self): self.files={}; self.runs=0; self.created_with=None
        async def create(self, task, ttl=3600): self.created_with=task; return task
        async def write_file(self,sid,path,content): self.files[path]=content
        async def read_file(self,sid,path): return self.files[path]
        async def exec(self,*args): return {"exit_code":0,"output":"passed","truncated":False}
        async def destroy(self,*args): pass
    sandbox=Sandbox()
    class Runtime:
        async def run(self,**kwargs):
            sandbox.runs += 1; sandbox.files["a.py"] = f"fixed {sandbox.runs}"
            return RuntimeResult(text="changed",total_tokens=1)
    class GitHub:
        pulls=0
        async def repository_snapshot(self,*args): return "base",[("a.py",b"old")]
        async def create_fix_pull_request(self,*args): self.pulls+=1; return {"id":2,"number":11,"html_url":"https://example/pr"}
    p=TaskProcessor(app.state.sessions,app.state.vault,app.state.settings,runtime=Runtime())
    p.sandbox=lambda: sandbox
    p.model=lambda agent, task_id=None: (SimpleNamespace(
        base_url="https://models.example", model="m", system_prompt="system", provider="p",
        model_timeout=5, tool_timeout=5, task_timeout=5, sandbox_ttl=3600,
        soft_step_limit=3, hard_step_limit=3, step_extension=1, loop_threshold=3,
        audit_snapshot=lambda: {},
    ), "key")
    reviews=0
    async def structured(*args):
        nonlocal reviews; reviews+=1
        return ReviewVerdict(verdict="changes_required",blocking_issues=[{"severity":"blocking","message":"retry","issue_type":"correctness"}],summary="retry",risk="medium")
    p.structured_agent=structured
    github=GitHub()
    analysis=IssueAnalysis(status="actionable",summary="fix",risk="low",suggested_plan=["edit"])
    asyncio.run(p.fix_issue(task_id,github,7,"owner/repo",10,{"default_branch":"main","install_command":"","test_command":"","lint_command":"","build_command":"","working_directory":".","additional_instructions":""},{"title":"bug","body":"body"},analysis))
    assert sandbox.runs == reviews == 2 and github.pulls == 0
    assert sandbox.created_with == f"{task_id}-attempt-2"
    with app.state.sessions() as db: assert db.get(Task,task_id).status == "failed_review"


def test_owner_decision_is_audited_and_resumed(client, app):
    with app.state.sessions.begin() as db:
        repository(db)
        task=Task(kind="issue",repository="owner/repo",number=12,event="issues.opened",delivery_id="owner",status="waiting_for_owner",data={"summary":"choose"})
        db.add(task);db.flush();task_id=task.id
    response=client.post(f"/api/tasks/{task_id}/decision",json={"decision":"Proceed with the small fix", "action":"implement"})
    assert response.status_code == 200
    with app.state.sessions() as db:
        task=db.get(Task,task_id)
        assert task.status == "queued" and task.data["owner_decision"].startswith("Proceed") and task.data["owner_decision_action"] == "implement"
        assert db.scalar(select(Timeline).where(Timeline.task_id==task_id,Timeline.kind=="owner_decision")).data["action"] == "implement"


def test_safely_interrupted_task_can_be_retried(client, app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=51, event="issues.opened", delivery_id="restart", status="interrupted", data={"error": "Service restarted"})
        db.add(task); db.flush(); task_id = task.id
    assert client.post(f"/api/tasks/{task_id}/retry").json()["status"] == "queued"


@pytest.mark.parametrize(("action", "expected_status", "close_calls"), [
    ("reject", "closed_without_change", 1),
    ("defer", "waiting_for_owner", 0),
])
def test_owner_control_signal_skips_worker_and_sandbox(app, action, expected_status, close_calls):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=52, event="issues.opened", delivery_id=action, status="running", data={"owner_decision": "owner decision", "owner_decision_action": action})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        closed = 0
        async def issue_context(self, *args): return {"issue": {"title": "A change", "body": "Please implement."}, "comments": []}
        async def close_issue(self, *args): self.closed += 1; return {"html_url": "https://example/issues/52"}
        async def repository_guidance(self, *args): raise AssertionError("owner control must run before guidance/model")

    github = GitHub()
    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def unexpected(*args): raise AssertionError("owner reject/defer must not call worker/model")
    processor.structured_agent = unexpected
    processor.sandbox = lambda: (_ for _ in ()).throw(AssertionError("owner reject/defer must not create sandbox"))
    asyncio.run(processor.process_issue(task_id, github, 7, "owner/repo", 52, {"default_branch": "main", "additional_instructions": ""}))
    assert github.closed == close_calls
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == expected_status
        assert not db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "sandbox_created"))


def test_owner_implement_allows_worker_route(app):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=53, event="issues.opened", delivery_id="implement", status="running", data={"owner_decision": "Implement it", "owner_decision_action": "implement"})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        async def issue_context(self, *args): return {"issue": {"title": "Fix calculation", "body": "Please implement."}, "comments": []}
        async def repository_guidance(self, *args): return "guidance"

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def analysis(*args): return IssueAnalysis(status="actionable", summary="clear", reason="clear", risk="low", suggested_plan=["fix"])
    worker_routes = []
    async def worker(*args): worker_routes.append(True)
    processor.structured_agent = analysis
    processor.fix_issue = worker
    asyncio.run(processor.process_issue(task_id, GitHub(), 7, "owner/repo", 53, {"default_branch": "main", "additional_instructions": ""}))
    assert worker_routes == [True]


@pytest.mark.parametrize(("worker_text", "expected_status", "event"), [
    ("The behavior is already fixed and tests pass.", "already_resolved", "already_resolved"),
    ("No code changes were needed because the implementation is already correct.", "already_resolved", "already_resolved"),
    ("Investigation completed without a patch.", "waiting_for_owner", "unexpected_no_change"),
])
def test_no_change_outcome_distinguishes_resolved_from_unexpected(app, worker_text, expected_status, event):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="issue", repository="owner/repo", number=54, event="issues.opened", delivery_id=event, status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class Sandbox:
        async def create(self, *args): return "sandbox"
        async def write_file(self, *args): pass
        async def read_file(self, *args): return "original"
        async def exec(self, *args): return {"exit_code": 0, "output": "tests pass", "truncated": False}
        async def destroy(self, *args): pass
    class Runtime:
        async def run(self, **kwargs): return RuntimeResult(text=worker_text, total_tokens=1)
    class GitHub:
        async def repository_snapshot(self, *args): return "base", [("a.js", b"original")]

    p = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings, runtime=Runtime())
    p.sandbox = lambda: Sandbox()
    p.model = lambda agent, task_id=None: (SimpleNamespace(base_url="https://models.example", model="m", system_prompt="system", provider="p", model_timeout=5, tool_timeout=5, task_timeout=5, sandbox_ttl=3600, soft_step_limit=3, hard_step_limit=3, step_extension=1, loop_threshold=3, audit_snapshot=lambda: {}), "key")
    analysis = IssueAnalysis(status="actionable", summary="fix", risk="low", suggested_plan=["edit"])
    asyncio.run(p.fix_issue(task_id, GitHub(), 7, "owner/repo", 54, {"default_branch":"main", "install_command":"", "test_command":"npm test", "lint_command":"", "build_command":"", "working_directory":".", "additional_instructions":""}, {"title":"bug", "body":"body"}, analysis))
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == expected_status and task.status != "failed_agent"
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == event))


@pytest.mark.parametrize(("title", "path", "expected_gate"), [
    ("Add a calculator history command", "src/history.js", "product_decision_required"),
    ("Harden request handling", "backend/maintainer/security.py", "high_risk_owner_gate"),
])
def test_external_pr_technical_pass_still_waits_for_deterministic_owner_gate(app, title, path, expected_gate):
    with app.state.sessions.begin() as db:
        repository(db)
        task = Task(kind="pull_request", repository="owner/repo", number=30, event="pull_request.opened", delivery_id=title, status="running", data={})
        db.add(task); db.flush(); task_id = task.id

    class GitHub:
        reviews = []
        async def pull_context(self, *args):
            return {"pull": {"title": title, "body": "Clean implementation", "draft": False, "user": {"login": "alice"}, "head": {"sha": "head", "ref": "feature", "repo": {"full_name": "alice/repo"}}, "base": {"ref": "main"}}, "files": [{"filename": path, "patch": "@@ -0,0 +1 @@\n+ok", "status": "added", "additions": 1, "deletions": 0}], "commits": [{}], "checks": {"check_runs": []}, "statuses": {"state": "success", "statuses": []}}
        async def repository_guidance(self, *args): return "guidance"
        async def review(self, *args): self.reviews.append(args); return {"id": 1, "html_url": "https://example/review"}

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    async def structured(*args): return ReviewVerdict(verdict="approved", summary="Technically sound", risk="low")
    processor.structured_agent = structured
    github = GitHub()
    asyncio.run(processor.process_pull(task_id, github, 7, "owner/repo", 30, {}))
    assert github.reviews == []
    with app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "waiting_for_owner" and task.data["technical_review"] == "passed" and task.data["owner_gate"] == expected_gate
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == expected_gate))


def test_feature_pr_bug_fix_resolves_technical_gate_but_keeps_product_gate(app):
    with app.state.sessions.begin() as db:
        repository(db)
        opened = Task(kind="pull_request", repository="owner/repo", number=31, event="pull_request.opened", delivery_id="feature-bug-opened", status="running", created=100, data={})
        db.add(opened); db.flush(); opened_id = opened.id

    class GitHub:
        head = "bad"
        reviews = []
        async def pull_context(self, installation, repo_name, number, previous=""):
            patch = "@@ -0,0 +1 @@\n+return a + b" if self.head == "bad" else "@@ -0,0 +1 @@\n+return a * b"
            return {"pull": {"title": "Add multiplication history feature", "body": "Adds a new product capability", "draft": False, "user": {"login": "alice"}, "head": {"sha": self.head, "ref": "feature", "repo": {"full_name": "alice/repo"}}, "base": {"ref": "main"}}, "files": [{"filename": "src/history.js", "patch": patch, "status": "modified", "additions": 1, "deletions": 1}], "aggregate_files": [{"filename": "src/history.js", "patch": patch}], "commits": [{}], "checks": {"check_runs": []}, "statuses": {"state": "success", "statuses": []}, "diff_source": "head_comparison" if previous else "pull", "diff_size": len(patch)}
        async def repository_guidance(self, *args): return "guidance"
        async def review(self, installation, repo_name, number, sha, event, body, comments):
            self.reviews.append(event); return {"id": len(self.reviews), "html_url": "https://example/review"}

    processor = TaskProcessor(app.state.sessions, app.state.vault, app.state.settings)
    verdicts = [
        ReviewVerdict(verdict="changes_required", summary="Logic bug", risk="medium", blocking_issues=[{"severity": "blocking", "path": "src/history.js", "line": 1, "message": "Multiplication uses addition", "issue_type": "correctness"}]),
        ReviewVerdict(verdict="approved", summary="Technical issue resolved", risk="low"),
    ]
    async def structured(*args): return verdicts.pop(0)
    processor.structured_agent = structured
    github = GitHub()
    asyncio.run(processor.process_pull(opened_id, github, 7, "owner/repo", 31, {}))
    with app.state.sessions.begin() as db:
        assert db.get(Task, opened_id).status == "waiting_for_contributor"
        sync = Task(kind="pull_request", repository="owner/repo", number=31, event="pull_request.synchronize", delivery_id="feature-bug-sync", status="running", created=101, data={})
        db.add(sync); db.flush(); sync_id = sync.id
    github.head = "fixed"
    asyncio.run(processor.process_pull(sync_id, github, 7, "owner/repo", 31, {}))
    assert github.reviews == ["REQUEST_CHANGES"]
    with app.state.sessions() as db:
        sync = db.get(Task, sync_id)
        assert sync.status == "waiting_for_owner" and sync.data["technical_review"] == "passed"
        assert sync.data["product_gate"]["classification"] == "product_feature"
        assert db.scalar(select(Timeline).where(Timeline.task_id == sync_id, Timeline.kind == "product_decision_required"))
