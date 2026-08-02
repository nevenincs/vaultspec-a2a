---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:44965ce7c859c484978dd77a046d83b99c5ab8c1cf3829011f6d344053df9b45'
step_id: 'S04'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove a provider exception's identity survives to the failure reason through real ingest

## Scope

- `src/vaultspec_a2a/streaming/tests/test_aggregator.py`

## Description

- Compile a real one-worker graph over the real worker node factory, driven by a
  real ACP chat model whose command is the repository's ACP protocol simulator - a
  real subprocess speaking real JSON-RPC over stdio - instructed to refuse the
  prompt with a vendor refusal string.
- Drive that graph through the real aggregator ingest path, not through a
  hand-constructed exception, so the whole repaired route runs: the provider raise
  site, the worker node's wrapper, the graph, and the ingest summarizer.
- Assert the reason ingest actually produced names the provider exception type,
  its JSON-RPC code, and the refusal text the simulator was given as INPUT.
- Assert the reason names the lane the turn ran on and does NOT name the chat
  model class, which is the identity it used to report.
- Assert the reason the durable column is offered is the same string the error
  frame carried, and that it fits the reason budget the durable column and its
  cross-repo consumer both enforce.

## Outcome

Both tests pass against the repaired path. The falsification evidence was
captured before any code changed: the same graph, driven through the same route
on the unmodified tree, produced

`Graph event stream failed unexpectedly: WorkerExecutionError: worker='coder'
model=AcpChatModel messages=2`

which fails every assertion in the first test - it names no provider exception,
no protocol code, none of the refusal text, and names the class rather than the
lane. After the Phase the same route produces

`Graph event stream failed unexpectedly: WorkerExecutionError: worker='coder'
model=claude messages=2 <- AcpPromptError[-32000]: ACP prompt failed:
{'code': -32000, 'message': 'Your credit balance is too low to access the
Anthropic API.'}`

Verified with `ruff format`, `ruff check`, whole-tree `ty check`, and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
streaming, graph node, and thread test packages: 594 passed, 2 deselected.

## Notes

No credential was spent and no served lane was called. The refusal is produced by
the repository's ACP simulator, which is a real subprocess implementing the real
protocol rather than an in-process stand-in for the provider client, and it is the
same harness the worker node's own integration tests already drive. Proving a
typed condition on a live served lane is a later Step of this Wave by design; this
Step proves the transport that condition will ride.

The simulator returns its prompt failure with one fixed JSON-RPC code and no
`data.errorKind`, so the discriminator each lane actually puts on the wire is not
exercised here. That discriminator is the next Phase's subject.

The graph is constructed with the state type cast, matching how the production
compiler and the worker node's own integration tests build one; the type checker
does not accept the state TypedDict against the graph's bound directly.
