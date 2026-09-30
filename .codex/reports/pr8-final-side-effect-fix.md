# PR #8 completed Review reuse: completion side-effect repair

Status: PR #8 remains Draft and unmerged. Phase 2 has not started.

## Root cause

The Controller already reused a completed Review's GitHub ID and URL without another POST. The reuse decision ended inside `github_action`, however. `process_pull` then updated the second Task to `reviewed` or `waiting_for_contributor` through the normal completion path. `change_status` published a fresh plugin completion event, and `process` called `task.finally` and the completion email path for the second Task. Thus GitHub writes were idempotent, but effect-level completion callbacks were not.

## Change

- When a completed Review is reused, `github_action` persists the source action ID, PR head, and current Task attempt on the new Task in the same transaction as the existing `pr_review_reused` audit event. The new Task still receives its own final status, Review URL, and normal `status_changed` timeline entry.
- For that exact reused head and attempt, `change_status` suppresses the duplicate `pr.reviewed` / `pr.changes_requested` plugin event and writes `review_completion_side_effects_skipped` to the Task timeline. `process` skips a second `task.finally` dispatch and completion report email. Task-started hooks and all unrelated Task outcomes remain unchanged.
- The marker is bound to head and attempt, so a later independent review on a new head or new attempt retains normal plugin lifecycle behavior. It carries no credential or secret.

## Regression coverage

`tests/test_review_recovery.py` now runs two real Controller Task lifecycles against a simulated GitHub Review API. Task A publishes one Review, emits one `pr.reviewed` event, calls its finalizer once, and sends one report. A second webhook Task reuses the saved Review and reaches `reviewed` with the same URL. It adds no Review POST, completion plugin event, finalizer call, or report email. Its own state and audit timeline remain visible. Separate cases confirm an old reuse marker does not suppress a later independent head or attempt.

## Validation

- PR #8 recovery tests: `44 passed, 1 warning`.
- Complete backend suite: `191 passed, 1 warning`. The warning is Starlette's existing AnyIO deprecation.
- `git diff --check`: passed.
- No GitHub Review, repository, or production service was mutated for these tests.

## Limits

This repairs duplication when a second Task reuses a completed Review action. GitHub's lack of an atomic Review idempotency key leaves the previously documented late-completion race after an explicitly authorized retry. Recovery and administrator authorization are unchanged. A Review action can be completed before its original Task finishes; if that Task later fails, its existing recovery path is still responsible for completing that Task's lifecycle.
