import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from sqlalchemy.exc import IntegrityError

from .db import Repository, Task, Timeline, WebhookDelivery


class GitHubError(RuntimeError):
    pass


def decode_github_content(value: str) -> bytes:
    """Decode GitHub's MIME-wrapped base64 while still rejecting invalid data."""
    try:
        compact = "".join(value.split())
        return base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error) as error:
        raise GitHubError("GitHub returned invalid base64 content") from error


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith("sha256=") or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


@dataclass
class CachedToken:
    value: str
    expires_at: float


class GitHubAppClient:
    def __init__(self, app_id: int, private_key: str, api_url: str = "https://api.github.com"):
        self.app_id, self.private_key, self.api_url = app_id, private_key, api_url.rstrip("/")
        self._tokens: dict[int, CachedToken] = {}

    def app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)}, self.private_key, algorithm="RS256")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.api_url + "/", timeout=30, follow_redirects=False, trust_env=False, headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "maintune/0.1.0-preview.2"})

    async def installation_token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at > time.time() + 120:
            return cached.value
        async with self.client() as client:
            response = await client.post(f"app/installations/{installation_id}/access_tokens", headers={"Authorization": f"Bearer {self.app_jwt()}"})
            if response.status_code >= 400:
                raise GitHubError(f"GitHub installation token request failed ({response.status_code})")
            body = response.json()
            # GitHub currently expires installation tokens after one hour. Refresh early.
            token = CachedToken(body["token"], time.time() + 3300)
            self._tokens[installation_id] = token
            return token.value

    async def request(self, installation_id: int, method: str, path: str, **kwargs) -> Any:
        token = await self.installation_token(installation_id)
        async with self.client() as client:
            response = await client.request(method, path.lstrip("/"), headers={"Authorization": f"Bearer {token}"}, **kwargs)
            if response.status_code >= 400:
                raise GitHubError(f"GitHub API {method} {path} failed ({response.status_code})")
            if response.status_code == 204:
                return None
            return response.json()

    async def paginated(self, installation_id: int, path: str, *, limit: int = 101) -> list[dict]:
        """Load enough complete pages to enforce the review safety limit."""
        items: list[dict] = []
        page = 1
        while len(items) < limit:
            page_size = min(100, limit - len(items))
            chunk = await self.request(
                installation_id,
                "GET",
                path,
                params={"per_page": page_size, "page": page},
            )
            if not isinstance(chunk, list):
                raise GitHubError(f"GitHub API GET {path} returned an invalid paginated response")
            items.extend(chunk)
            if len(chunk) < page_size:
                break
            page += 1
        return items[:limit]

    async def installations(self) -> list[dict]:
        async with self.client() as client:
            response = await client.get("app/installations", headers={"Authorization": f"Bearer {self.app_jwt()}"})
            if response.status_code >= 400:
                raise GitHubError(f"GitHub App authentication failed ({response.status_code})")
            return response.json()

    async def issue_context(self, installation_id: int, repo: str, number: int) -> dict:
        issue = await self.request(installation_id, "GET", f"repos/{repo}/issues/{number}")
        comments = await self.request(installation_id, "GET", f"repos/{repo}/issues/{number}/comments", params={"per_page": 100})
        return {"issue": issue, "comments": comments}

    async def pull_context(self, installation_id: int, repo: str, number: int, previous_head_sha: str = "") -> dict:
        # Always reload every source of review evidence from GitHub. Webhook payloads
        # deliberately carry identifiers only and are never used as review context.
        pull = await self.request(installation_id, "GET", f"repos/{repo}/pulls/{number}")
        head_sha = (pull.get("head") or {}).get("sha") or ""
        if not head_sha:
            raise GitHubError("GitHub pull request response omitted the current head SHA")
        aggregate_files = await self.paginated(installation_id, f"repos/{repo}/pulls/{number}/files")
        commits = await self.paginated(installation_id, f"repos/{repo}/pulls/{number}/commits")
        checks = await self.request(installation_id, "GET", f"repos/{repo}/commits/{head_sha}/check-runs", params={"per_page": 100})
        statuses = await self.request(installation_id, "GET", f"repos/{repo}/commits/{head_sha}/status")

        latest_files: list[dict] = []
        if previous_head_sha and previous_head_sha != head_sha:
            comparison = await self.request(installation_id, "GET", f"repos/{repo}/compare/{previous_head_sha}...{head_sha}")
            latest_files = comparison.get("files") or []
        review_files = aggregate_files or latest_files
        diff_size = sum(len(item.get("patch") or "") for item in review_files)
        if commits and (not review_files or diff_size == 0):
            raise GitHubError("GitHub returned commits but no reviewable pull request diff")
        return {
            "pull": pull,
            "files": review_files,
            "aggregate_files": aggregate_files,
            "latest_files": latest_files,
            "commits": commits,
            "checks": checks,
            "statuses": statuses,
            "diff_source": "pull" if aggregate_files else "head_comparison",
            "diff_size": diff_size,
        }

    async def comment(self, installation_id: int, repo: str, number: int, body: str) -> dict:
        return await self.request(installation_id, "POST", f"repos/{repo}/issues/{number}/comments", json={"body": body})

    async def close_issue(self, installation_id: int, repo: str, number: int) -> dict:
        """Close an Issue through the GitHub Issues API under Controller policy."""
        return await self.request(installation_id, "PATCH", f"repos/{repo}/issues/{number}", json={"state": "closed"})

    async def repository_guidance(self, installation_id: int, repo: str, ref: str) -> str:
        documents = []
        for path in ("AGENTS.md", "CONTRIBUTING.md", "README.md"):
            try:
                item = await self.request(installation_id, "GET", f"repos/{repo}/contents/{path}", params={"ref": ref})
                if item.get("encoding") == "base64" and int(item.get("size") or 0) <= 200_000:
                    documents.append(f"## {path}\n" + decode_github_content(item["content"]).decode("utf-8", errors="replace"))
            except GitHubError:
                continue
        return "\n\n".join(documents)[:300_000]

    async def repository_snapshot(self, installation_id: int, repo: str, ref: str) -> tuple[str, list[tuple[str, bytes]]]:
        commit = await self.request(installation_id, "GET", f"repos/{repo}/commits/{ref}")
        sha = commit["sha"]
        tree = await self.request(installation_id, "GET", f"repos/{repo}/git/trees/{commit['commit']['tree']['sha']}", params={"recursive": "1"})
        entries = [item for item in tree.get("tree", []) if item.get("type") == "blob"]
        if tree.get("truncated") or len(entries) > 1000:
            raise GitHubError("Repository snapshot exceeds the stage-2 safety limit")
        files, total = [], 0
        for item in entries:
            if int(item.get("size") or 0) > 1_000_000:
                continue
            blob = await self.request(installation_id, "GET", f"repos/{repo}/git/blobs/{item['sha']}")
            if blob.get("encoding") != "base64":
                continue
            content = decode_github_content(blob["content"])
            total += len(content)
            if total > 20_000_000:
                raise GitHubError("Repository snapshot exceeds 20 MB")
            files.append((item["path"], content))
        return sha, files

    async def create_fix_pull_request(self, installation_id: int, repo: str, base_sha: str, base_branch: str, task_id: str, issue_number: int, changed: list[tuple[str, str]], summary: str, tests: str) -> dict:
        branch = f"ai-maintainer/fix-{issue_number}-{task_id[:8]}"
        existing = None
        try:
            existing = await self.request(installation_id, "GET", f"repos/{repo}/git/ref/heads/{branch}")
        except GitHubError:
            pass
        if existing:
            pulls = await self.request(installation_id, "GET", f"repos/{repo}/pulls", params={"head": f"{repo.split('/')[0]}:{branch}", "state": "all"})
            if pulls:
                return pulls[0]
            raise GitHubError("Fix branch already exists without a matching PR; owner review required")
        base = await self.request(installation_id, "GET", f"repos/{repo}/git/commits/{base_sha}")
        tree_items = []
        for path, content in changed:
            blob = await self.request(installation_id, "POST", f"repos/{repo}/git/blobs", json={"content": content, "encoding": "utf-8"})
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = await self.request(installation_id, "POST", f"repos/{repo}/git/trees", json={"base_tree": base["tree"]["sha"], "tree": tree_items})
        commit = await self.request(installation_id, "POST", f"repos/{repo}/git/commits", json={"message": f"fix: address issue #{issue_number}", "tree": tree["sha"], "parents": [base_sha]})
        await self.request(installation_id, "POST", f"repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        body = f"{summary}\n\n## Tests\n{tests}\n\nGenerated by Maintune with independent review.\n\nCloses #{issue_number}\n\n<!-- ai-maintainer:{task_id}:fix-pr -->"
        return await self.request(installation_id, "POST", f"repos/{repo}/pulls", json={"title": f"Fix #{issue_number}: {summary[:120]}", "head": branch, "base": base_branch, "body": body})

    async def review(self, installation_id: int, repo: str, number: int, commit_id: str, event: str, body: str, comments: list[dict]) -> dict:
        payload: dict[str, Any] = {"commit_id": commit_id, "event": event, "body": body}
        if comments:
            payload["comments"] = comments
        return await self.request(installation_id, "POST", f"repos/{repo}/pulls/{number}/reviews", json=payload)

    async def merge_pull_request(self, installation_id: int, repo: str, number: int, head_sha: str) -> dict:
        result = await self.request(installation_id, "PUT", f"repos/{repo}/pulls/{number}/merge", json={"sha": head_sha, "merge_method": "squash"})
        if not result.get("merged"):
            raise GitHubError("GitHub declined the deterministic merge request")
        return result


SUPPORTED = {
    "issues": {"opened", "edited", "reopened"},
    "issue_comment": {"created"},
    "pull_request": {"opened", "synchronize", "reopened", "ready_for_review"},
}


def ingest_webhook(db, delivery_id: str, event: str, body: bytes, payload: dict) -> tuple[WebhookDelivery, Task | None, bool]:
    existing = db.get(WebhookDelivery, delivery_id)
    if existing:
        return existing, db.get(Task, existing.task_id) if existing.task_id else None, True
    action = str(payload.get("action") or "")
    repo_name = (payload.get("repository") or {}).get("full_name")
    delivery = WebhookDelivery(delivery_id=delivery_id, event=event, action=action, repository=repo_name, payload_hash=hashlib.sha256(body).hexdigest())
    db.add(delivery)
    repository = db.get(Repository, repo_name) if repo_name else None
    if event not in SUPPORTED or action not in SUPPORTED[event]:
        delivery.status = "ignored_event"
        return delivery, None, False
    if not repository or not repository.data.get("enabled"):
        delivery.status = "ignored_repository"
        return delivery, None, False
    kind = "issue" if event in {"issues", "issue_comment"} else "pull_request"
    number = int((payload.get("issue") or payload.get("pull_request") or {}).get("number", 0))
    if not number:
        delivery.status = "invalid_payload"
        return delivery, None, False
    if kind == "issue" and not repository.data.get("auto_handle_issues"):
        delivery.status = "ignored_policy"
        return delivery, None, False
    if kind == "pull_request" and not repository.data.get("auto_review_prs"):
        delivery.status = "ignored_policy"
        return delivery, None, False
    if event == "issue_comment":
        comment_author = (payload.get("comment") or {}).get("user") or {}
        sender = (payload.get("sender") or {})
        # A clarification posted by this GitHub App also emits an
        # issue_comment webhook.  It is evidence of our own outbound action,
        # never a contributor reply and must not resume the task.
        if comment_author.get("type") == "Bot" or sender.get("type") == "Bot" or str(comment_author.get("login", "")).endswith("[bot]"):
            delivery.status = "ignored_bot_comment"
            return delivery, None, False
        waiting = db.query(Task).filter(Task.repository == repo_name, Task.number == number, Task.kind == "issue", Task.status == "waiting_for_contributor").order_by(Task.created.desc()).first()
        if not waiting:
            delivery.status = "ignored_comment"
            return delivery, None, False
        waiting.status, waiting.event = "queued", "issue_comment.created"
        waiting.data = {**waiting.data, "resume_delivery": delivery_id}
        task = waiting
        db.add(Timeline(task_id=task.id, kind="contributor_reply_received", data={"delivery_id": delivery_id, "author": (payload.get("comment") or {}).get("user", {}).get("login"), "comment_id": (payload.get("comment") or {}).get("id")}))
    else:
        task = Task(kind=kind, repository=repo_name, number=number, event=f"{event}.{action}", delivery_id=delivery_id, data={"sender": (payload.get("sender") or {}).get("login"), "installation_id": (payload.get("installation") or {}).get("id")})
        db.add(task)
        db.flush()
    delivery.task_id, delivery.status = task.id, "queued"
    db.add(Timeline(task_id=task.id, kind="webhook_received", data={"event": event, "action": action, "delivery_id": delivery_id}))
    return delivery, task, False
