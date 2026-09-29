# SPDX-License-Identifier: AGPL-3.0-only
"""Admin recovery of ambiguous PR review writes; never blindly replay a POST."""
import hashlib
import json
import time
import uuid
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, update

from .db import Outbox, Repository, Task, Timeline


class RecoveryConflict(ValueError):
    pass


class RecoveryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    attempts: int = Field(ge=1)
    head_sha: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    retry_authorized: StrictBool = False
    reason: str = Field(min_length=10, max_length=2000)


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot(sessions, task_id):
    with sessions() as db:
        task = db.get(Task, task_id)
        if not task or task.kind != "pull_request" or not (task.status.startswith("failed_") or task.status == "interrupted"):
            raise RecoveryConflict("A failed or interrupted PR task is required")
        actions = list(db.scalars(select(Outbox).where(Outbox.task_id == task_id, Outbox.status.in_(("unknown", "executing", "reconciling")))))
        if len(actions) != 1 or actions[0].kind != "pr_review" or actions[0].status != "unknown":
            raise RecoveryConflict("Exactly one unknown PR review and no active external action is required")
        action = actions[0]
        repo = db.get(Repository, task.repository)
        if not repo or not repo.data.get("enabled", False) or not repo.data.get("auto_review_prs", False):
            raise RecoveryConflict("Repository review access is disabled")
        installation = task.data.get("installation_id") or repo.installation_id
        if not installation or (repo.installation_id and repo.installation_id != installation):
            raise RecoveryConflict("Repository installation changed")
        payload = action.data.get("review_request")
        if payload is None:
            # Preview 3 stored only head/event. Recover only the unambiguous
            # legacy case; never guess inline comments or appended CI prose.
            event = db.scalar(select(Timeline).where(Timeline.task_id == task_id,
                Timeline.kind == "pr_review_completed", Timeline.timestamp <= action.created).order_by(Timeline.timestamp.desc()))
            review = event.data if event else {}
            if (action.data.get("event") != "APPROVE" or review.get("verdict") != "approved"
                    or review.get("blocking_issues") or review.get("suggestions")
                    or review.get("head_sha") != action.data.get("head_sha") or not review.get("summary")):
                raise RecoveryConflict("Original review payload is unavailable; do not infer or replay it")
            payload = {"commit_id": action.data["head_sha"], "event": "APPROVE", "body": review["summary"], "comments": []}
        if (set(payload) != {"commit_id", "event", "body", "comments"}
                or payload["commit_id"] != action.data.get("head_sha")
                or payload["event"] != action.data.get("event")
                or payload["event"] not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}
                or not isinstance(payload["body"], str) or not isinstance(payload["comments"], list)
                or task.data.get("head_sha") != payload["commit_id"]):
            raise RecoveryConflict("Original review payload or task head is inconsistent")
        expected_key = f"pr-review:{task.repository}:{task.number}:{payload['commit_id']}:{payload['event']}"
        if action.action_key != expected_key:
            raise RecoveryConflict("Review action identity is inconsistent")
        return {"action_id": action.id, "attempts": action.attempts, "task_id": task.id,
                "repository": task.repository, "number": task.number, "installation": installation,
                "head_sha": payload["commit_id"], "payload_sha256": payload_hash(payload),
                "payload": payload, "data": dict(action.data),
                "last_attempt": action.data.get("attempt_started_at", action.created)}


async def complete_list(github, installation, path):
    # A cap is a conflict, not evidence of absence. Always read the final page.
    rows = await github.paginated(installation, path, limit=1001)
    if len(rows) >= 1001:
        raise RecoveryConflict("GitHub result exceeds reconciliation limit")
    return rows


def comment_keys(comments):
    return Counter((x.get("path"), x.get("body"), x.get("line") or x.get("original_line"),
                    x.get("side", "RIGHT"), x.get("start_line"), x.get("start_side")) for x in comments)


async def inspect_remote(github, item):
    installation, repo, number = item["installation"], item["repository"], item["number"]
    pull = await github.request(installation, "GET", f"repos/{repo}/pulls/{number}")
    if pull.get("state") != "open" or pull.get("merged") or pull.get("draft") or pull.get("head", {}).get("sha") != item["head_sha"]:
        raise RecoveryConflict("PR is closed, draft, merged, or its head changed")
    author = await github.review_author()
    rows = await complete_list(github, installation, f"repos/{repo}/pulls/{number}/reviews")
    payload = item["payload"]
    expected_state = {"APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES_REQUESTED", "COMMENT": "COMMENTED"}[payload["event"]]
    matches = []
    for review in rows:
        user = review.get("user") or {}
        if user.get("type") != "Bot" or user.get("login") != author:
            continue
        if review.get("state") == "PENDING":
            raise RecoveryConflict("The publishing App has a pending review; manual inspection is required")
        if review.get("commit_id") != item["head_sha"]:
            continue
        if review.get("body") != payload["body"] or review.get("state") != expected_state or not review.get("submitted_at"):
            raise RecoveryConflict("An App review for this head differs from the reserved review")
        identifier = review.get("id")
        if type(identifier) is not int or identifier <= 0:
            raise RecoveryConflict("GitHub review identity is invalid")
        comments = await complete_list(github, installation, f"repos/{repo}/pulls/{number}/reviews/{identifier}/comments")
        if comment_keys(comments) != comment_keys(payload["comments"]):
            raise RecoveryConflict("Published inline comments differ from the reserved review")
        if not isinstance(review.get("html_url"), str) or not review["html_url"].startswith("https://"):
            raise RecoveryConflict("Published review URL is unavailable")
        matches.append(review)
    if len(matches) > 1:
        raise RecoveryConflict("Multiple matching reviews exist; manual inspection is required")
    return matches[0] if matches else None


async def inspect_review(processor, task_id):
    item = snapshot(processor.sessions, task_id)
    match = await inspect_remote(processor.app_client(), item)
    return {key: item[key] for key in ("action_id", "attempts", "head_sha", "payload_sha256")} | {
        "outcome": "found" if match else "not_found",
        "review_url": match.get("html_url") if match else None,
        "request": item["payload"],
        "note": "not_found is not proof that the old request cannot complete; a retry requires an explicit admin decision."}


async def recover_review(processor, task_id, decision):
    sessions = processor.sessions
    item = snapshot(sessions, task_id)
    for key in ("action_id", "attempts", "head_sha", "payload_sha256"):
        if getattr(decision, key) != item[key]:
            raise RecoveryConflict("Recovery preview changed; inspect the action again")
    claim = uuid.uuid4().hex
    claimed_data = {**item["data"], "recovery_claim": claim}
    with sessions.begin() as db:
        changed = db.execute(update(Outbox).where(Outbox.id == item["action_id"], Outbox.status == "unknown",
            Outbox.attempts == item["attempts"], Outbox.data == item["data"]).values(status="reconciling", data=claimed_data)).rowcount
        if changed != 1:
            raise RecoveryConflict("Another recovery already claimed this action")
    try:
        match = await inspect_remote(processor.app_client(), item)
        if not match and not decision.retry_authorized:
            raise RecoveryConflict("No review found; explicit admin retry authorization is required")
        if not match and time.time() - item["last_attempt"] < 120:
            raise RecoveryConflict("Wait at least two minutes after the last attempt before authorizing a retry")
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            repo = db.get(Repository, item["repository"])
            if (not task or task.data.get("head_sha") != item["head_sha"]
                    or not (task.status.startswith("failed_") or task.status == "interrupted")
                    or (task.data.get("installation_id") or (repo.installation_id if repo else None)) != item["installation"]
                    or not repo or not repo.data.get("enabled", False) or not repo.data.get("auto_review_prs", False)
                    or (repo.installation_id and repo.installation_id != item["installation"])):
                raise RecoveryConflict("Task or repository changed during reconciliation")
            data = {**item["data"], "review_request": item["payload"], "recovery": {
                "at": time.time(), "reason": decision.reason, "retry_authorized": not bool(match),
                "installation_id": item["installation"],
                "payload_sha256": item["payload_sha256"]}}
            changed = db.execute(update(Outbox).where(Outbox.id == item["action_id"], Outbox.status == "reconciling",
                Outbox.data == claimed_data).values(status="completed" if match else "pending", data=data,
                external_id=str(match["id"]) if match else None, external_url=match["html_url"] if match else None,
                error=None)).rowcount
            if changed != 1:
                raise RecoveryConflict("Recovery claim changed")
            task.status, task.lease_until = "queued", None
            task.data = {key: value for key, value in task.data.items() if key not in {"error", "failure"}}
            db.add(Timeline(task_id=task_id, kind="github_review_reconciled" if match else "github_review_retry_authorized",
                data={"action_id": item["action_id"], "head_sha": item["head_sha"], "payload_sha256": item["payload_sha256"],
                      "reason": decision.reason, "source": "admin_api", "review_url": match["html_url"] if match else None}))
        return {"status": "queued", "outcome": "reconciled" if match else "retry_authorized",
                "review_url": match["html_url"] if match else None}
    finally:
        # Failed/cancelled checks keep the uncertain write protected. A process
        # crash is handled by the existing startup recovery, extended below.
        with sessions.begin() as db:
            db.execute(update(Outbox).where(Outbox.id == item["action_id"], Outbox.status == "reconciling",
                Outbox.data == claimed_data).values(status="unknown", data=item["data"]))
