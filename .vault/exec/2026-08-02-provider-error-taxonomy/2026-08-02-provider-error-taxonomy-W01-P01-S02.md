---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8077a012d19fdb2bb16684110f82773b822b6b3908e7d2ad4dd3e83867837ca7'
step_id: 'S02'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Name the resolved provider lane and model id instead of the model class

## Scope

- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_worker.py`

## Description

- Add `_describe_worker_model` to the worker node: it names the provider lane and
  the concrete model id off the resolved model instance the turn actually
  invoked, joined as `lane/model-id`.
- Read the lane and the model id off that same instance rather than off the
  provider that was requested, because a fallback chain makes the two differ and
  only the resolved one is a fact about the run.
- Accept only a short, single-line identity; a value over 64 characters is
  declined rather than truncated, since the label reaches a client-visible
  failure reason alongside the provider's own message.
- Degrade to the class name for a model declaring neither - the in-process mock,
  a hosted API model - so the report is less precise but never invented.
- Rename the wrapper's parameter from `model_type` to `model_label`, because it
  no longer carries a type, and use the same label for the pre-invocation debug
  log so the log and the failure report agree.
- Cover the lane naming against the real ACP chat model, and cover both the
  fallback and the declined-overlong path.

## Outcome

The wrapper stops reporting the class that carried a turn and starts reporting
what the turn ran on. One class serves every ACP lane behind a redirected base
URL, so the old label could not distinguish which vendor was called; a
simulated failure on a model declaring the zai lane and the glm-4.6 model now
reports `zai/glm-4.6` where it previously reported `AcpChatModel`.

Driven end to end through a real ACP subprocess, a real worker node and a real
compiled graph, the reason moved from

`worker='coder' model=AcpChatModel messages=2 | AcpPromptError[-32000]: ...`

to

`worker='coder' model=claude messages=2 | AcpPromptError[-32000]: ...`

The probe model declares a lane but no model id, which is the documented
degradation: the lane alone is reported rather than a guess. A production model
carries both, because the factory sets the concrete model on the instance.

Verified with `ruff format`, `ruff check`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
streaming, graph node, and thread test packages: 587 passed, 2 deselected.

## Notes

The in-process mock declares no lane and sets its model name to the agent id, so
its label is now the agent id rather than the class name. That is the mock's own
declaration and it is not a served lane, so it is left as it is rather than
special-cased.

The label is composed only from bounded configuration values already held on the
model instance. Nothing reads the spawn command, the environment, or the
workspace path, so widening the label did not widen what a failure reason can
disclose.
