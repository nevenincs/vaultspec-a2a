---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:dad6336d96f4d3fa64b2f08e0bfba3c67983029f1d3fbf7860421e24c483762c'
step_id: 'S01'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Retain the provider exception type, message, and code on the worker wrapper

## Scope

- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/thread/errors.py`
- `src/vaultspec_a2a/thread/tests/test_errors.py`

## Description

- Add `describe_exception` to `src/vaultspec_a2a/thread/errors.py`: a bounded,
  single-line rendering of one exception's own type, numeric or string code, and
  message. It prefers a published `message` attribute over `str`, following the
  convention the ACP error classes already set, and is deliberately
  non-recursive so a caller walking a cause chain composes the links itself.
- Cap the rendered message portion at 240 characters and collapse embedded
  newlines, so no single link can consume the whole client-visible reason budget.
- Give `WorkerExecutionError` a keyword-only `cause`. Its `str` now folds in the
  rendered identity of that cause; its `message` attribute keeps the cause-free
  worker attribution so a cause-chain walker never reports the same provider
  fault twice.
- Pass the caught exception to the wrapper in `_wrap_worker_exception`, which
  previously chained it onto `__cause__` and discarded it from the message.
- Cover the new rendering against the real shipped ACP prompt error rather than
  a stand-in, and pin the cause-free attribution the walker depends on.

## Outcome

A provider fault raised inside a worker node now names itself on the wrapper. The
same simulated credit-balance failure, driven through a real ACP subprocess, a
real worker node and a real compiled graph, changed from

`worker='coder' model=AcpChatModel messages=2`

to

`worker='coder' model=AcpChatModel messages=2 | AcpPromptError[-32000]: ACP
prompt failed: {'code': -32000, 'message': 'Your credit balance is too low to
access the Anthropic API.'}`

The provider's exception type, its JSON-RPC code, and its own message all
survive. The model identity is still the class name; naming the resolved lane and
model id is the next Step's work.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check`, and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
streaming, graph node, and thread test packages: 584 passed, 2 deselected.

## Notes

The wrapper hunk in `src/vaultspec_a2a/graph/nodes/worker.py` did not land in this
Step's own commit. A concurrent writer in the same shared worktree committed that
file - carrying an unrelated node-protocol change of their own - while this Step
was verifying, and swept the wrapper hunk into their commit. The change is intact
and on the branch; it was not staged here, and no history was rewritten to
reclaim it. The remaining files were staged by explicit path.

Two observations recorded rather than acted on. First, the rendered detail is
assembled only from the exception's own type, code and message; nothing
interpolates command lines, environment values, or filesystem paths, but a
provider whose own message embeds such a value would still carry it to a client,
and no general redaction exists in the tree to prevent that. Second, the ACP
prompt error's own message embeds the entire raw JSON-RPC error object, so a
vendor-shaped payload rides the reason under the cap. Typed carriage of that
payload is the condition vocabulary's job in the next Phase.
