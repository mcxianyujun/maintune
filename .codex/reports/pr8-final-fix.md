# PR #8 final reliability repair

Status: local repair prepared for maintainer review. PR #8 is **not merged**. Phase 2 is not started.

## Root causes

1. `ingest_webhook` creates PR Tasks without `head_sha`. The review writer saved the head in its Outbox, but not in the Task. The administrator recovery endpoint required `Task.data.head_sha` to equal the Outbox request head, so the first real ambiguous write could not be reconciled.
2. Review guards searched Outbox rows by `task_id`. A second webhook delivery creates a new Task, so it could publish another review for the same repository, PR and head while the first write remained unknown. The former action key also included the review event, allowing a different event for the same head to reserve a separate action.

## Implementation

- Before a new Review POST, the Controller persists the repository and PR number (Task columns and Outbox snapshot), installation, head SHA, event, exact review request and SHA-256 request digest. The Task records the head, event and digest before Outbox execution. Recovery verifies that the Task and saved request still agree. A changed retry request cannot overwrite the original recovery context.
- New review actions use one Outbox identity per repository, PR and head. Before reservation, the Controller searches all review Outboxes for that PR/head, across webhook Tasks. A completed equivalent action is reused without POST; an unknown, executing, reconciling, pending, or different action blocks the new write. A new Task records the referenced action ID and status in its timeline for audit.
- Existing event-suffixed action keys remain readable and recoverable. For older records that saved an exact Outbox request but omitted Task head, administrator reconciliation can use that saved request and check the current GitHub head. New records must have the complete Task context. Administrator-only recovery, final remote inspection, and explicit retry authorization remain unchanged.

## State model

`pending -> executing -> completed` remains the successful path. An exception or cancellation during POST moves `executing -> unknown`; startup recovery handles interrupted `executing` and `reconciling` records. An unknown result can only move through administrator reconciliation, then to `completed` if the original Review is found or to authorized `pending` retry if it is not. A second webhook Task does not bypass these states; it reuses a completed equivalent result or waits for the original action's reconciliation. Different content or event for the same head remains blocked for manual inspection.

## Validation

- `tests/test_review_recovery.py`: webhook-created Task without prefilled head; saved context and administrator recovery; changed context rejection; new equivalent/different-event webhook Tasks blocked by an unknown action; completed equivalent action reused without a second POST; original cancellation, restart, authorization and delayed-success coverage retained.
- Targeted regression suite: `42 passed` (the PR #8 recovery tests plus the existing real external-review flow). Full backend suite: `188 passed, 1 warning` on Windows; the warning is Starlette's existing AnyIO deprecation. `git diff --check` passed.

## Remaining limits

- GitHub Review creation has no atomic remote idempotency key. After an authorized retry's final inspection, a very late completion of the original request could still race with the retry. The existing two-minute delay, repeat inspection and explicit administrator decision reduce but cannot eliminate this risk.
- The existing SQLite Outbox unique key prevents two concurrent new Tasks from posting with the same PR/head identity. A losing reservation may receive a database conflict and require normal task retry; it cannot create a second Review.
- Historical actions without a saved exact request remain recoverable only in the narrowly documented clean-approval case. Ambiguous historical payloads are deliberately rejected.
