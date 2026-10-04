---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:b15aa4093a842e5cc993e54294cde7a7001c638705d7890f70f7dcba58ffb33f'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-reference]]"
---

# `a2a-edge-conformance` audit: `Authoring tool retry identity security remediation`

## Scope

Security finding supplied by the user on 2026-10-04: mutating authoring tool retries receive fresh idempotency keys. The user explicitly requested a fix. This is direct, session-bounded execution under the accepted authoring placement, envelope, stable replay, token and lifecycle constraints in `2026-07-14-a2a-edge-conformance-adr` R3/R4/R7 and its linked reference. No new plan or engine API change is required.

The reviewed working-tree patch covers `authoring/catalog.py`, new `authoring/_tool_calls.py`, `control/state_layout.py`, the MCP bridge and stdio settings, provider authoring bindings, worker role scope and the corresponding tests. Independent read-only boundary investigation and candidate review were performed. Corrective changes were reviewed by the implementing agent against the final diff and verified through the affected boundaries. Concurrent changes outside this inventory are excluded.

Code discovery attempted project-locked semantic search. It returned `index_unverifiable`; service status reported failed indexing jobs. Discovery continued with the supplied epicenter files, direct callers and targeted symbol searches. Vault search and the full ADR listing supplied governing coverage.

## Findings

### mutation-retry-identity | medium | Fresh dispatch identities defeated engine deduplication

Type: security / replay integrity. Status: resolved in this patch. Before correction, each call through `src/vaultspec_a2a/authoring/catalog.py` minted separate fresh UUIDs for its key and engine tool-call ID. A repeated logical mutation therefore appeared new. The dispatcher now requires a stable, engine-valid logical identity, stores its input fingerprint and original lifecycle references before delivery, derives a deterministic run/role/command/call/lifecycle key and rejects conflicting input. Completed replays cannot roll back lifecycle state. The credential-free journal binds its version, run and role owner and survives bridge restarts. No document content, response body or actor credential is persisted.

The provider passes the role scope and absolute journal path to the spawned bridge. MCP carries identity outside model arguments as `_meta["vaultspec.dev/tool-call-id"]`; connection-local JSON-RPC request IDs and progress tokens are not accepted as stable identities. Missing identity refuses mutations before session creation or execute delivery. Read-only calls remain usable without identity. `src/vaultspec_a2a/authoring/client.py` already retained its envelope across its internal bearer-refresh retry and is excluded from this fix's inventory.

### misleading-idempotency-hint | medium | An idempotency obligation was advertised as duplicate safety

Type: protocol contract. Status: resolved. `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py:145` advertises `idempotent_hint` only for read-only tools. Mutations continue to preserve the private catalog requirement without claiming that separately identified calls have no additional effect. Real MCP serialization tests cover the annotation.

### definite-rejection-blocks-correction | medium | The first candidate left rejected requests pending

Type: availability / error recovery. Status: resolved before completion. Independent review reproduced a definite HTTP 400 refusal followed by permanent refusal of corrected calls, including after dispatcher reconstruction. The final dispatcher records HTTP 400/401/403/404/422 as terminal rejected identities and allows a corrected operation with a new identity. Reusing a rejected identity refuses explicitly. I/O loss, server errors and unresolved conflicts retain the prepared identity. Parameterized real HTTP tests cover each definite rejection, and HTTP 503 coverage proves ambiguous delivery keeps the original envelope.

### isolated-provider-journal-access | high | The first journal location was inaccessible to the Linux provider identity

Type: platform / functional regression. Status: resolved before completion. Independent review confirmed that agent UID 1002 cannot traverse the service-owned mode-0700 state home. The final path helper shares only the credential-free journal directory through the provider's existing managed workspace when identity isolation is configured. The private service home is unchanged. Directory ownership and POSIX identity prerequisites are checked before sharing access; ordinary profiles retain the journal under the configured state home.

A real worker-image proof used the production provider binding builder and identity launcher, spawned the actual MCP bridge as UID 1002 twice, dropped the first execute response and asserted identical envelopes after process restart. It also asserted that the service home remains mode 0700 and inaccessible to the agent. The retained helper is in the repository-targeted Codex Security artifact collection at `artifacts/validation/linux_authoring_replay.py`.

### native-provider-logical-metadata-proof | medium | Native CLI emission of logical call metadata remains unproven

Type: integration / capability evidence. Status: open follow-up; owner: provider integration. This patch accepts explicit provider/MCP identity and safely refuses callers that omit it. It does not add a native Claude/Codex adapter's retry-identity emission or prove a complete real-model authoring turn on those lanes. A follow-up must establish a native, stable, persisted call ID and demonstrate metadata propagation across a provider retry; it must not substitute a request counter, progress token, payload hash or generated per-attempt UUID. Until that proof exists, callers without the metadata receive an error for mutations. This is the requested fail-closed behavior, not a claim of provider capability.

### authoring-journal-retention | low | Completed journal rows have no lifecycle reclamation policy

Type: operations / storage retention. Status: open follow-up; owner: runtime lifecycle. Run/role journals intentionally retain completed identities so reconnects and late replays cannot become new mutations. Define a terminal-run retention and reclamation policy before deleting these records; eviction during a replayable run would break the invariant. No cleanup policy is introduced by this focused fix.

### stdio-bearer-refresh-wiring | low | The stdio bridge omits the existing bearer resolver

Type: reliability / existing sibling debt. Status: open follow-up; owner: authoring integration. `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py` constructs its client without the worker catalog fetcher's bearer resolver. This is outside retry identity remediation and was not changed. An engine bearer rotation therefore remains an agent-visible bridge failure; it is a definite rejection rather than permission to mint a fresh mutation identity.

### native-provider-identity-mapping | medium | Native logical metadata was ignored

Type: integration / replay identity. Status: implementation corrected, completed native-provider turn proof pending. Owner: provider integration. S01 consumes Codex `_meta.callId` only on the Codex launch and Claude/Z.ai `_meta["claudecode/toolUseId"]` only on their ACP launch. Other providers require the explicit namespaced key. Native identity is retained in the journal and command envelope without request counters, progress tokens, payload hashes or retry UUIDs. The Codex upstream `codex-rs/core/src/mcp_tool_call.rs::build_mcp_tool_call_request_meta` uses its native call_id; the installed Claude binary contains the native metadata key. These support the mapping but do not certify native provider resume semantics.

Real stdio lost-response/restart tests passed for all three metadata sources. The attempted real Codex turn skipped because the current served catalog selector is absent. S01 remains open pending native proof; the user was asked for a subscription-model selection preference while independent work continues. Focused authoring/replay coverage passed 24 tests; provider source-selection and trusted launch correction passed four tests. Ruff lint/format and full project type checks passed. Review verdict: PENDING for native capability evidence, with no high or critical source issue in the mapping diff.

### trusted-launch-test-contract-drift | low | The config test expected unresolved uvx

Type: verification / sibling contract drift. Status: resolved. The broader config run passed 108 tests and failed one stale literal `uvx` assertion after trusted launch began emitting an absolute executable. The corrected test checks absolute authority and the uvx executable identity. The focused rerun passed. Native metadata selection is also asserted in the rendered Codex config and ACP provider attachment tests.


## Verification

Final review verdict: PASS for the requested replay-integrity and MCP-annotation boundary, with the classified follow-ups above. The original failure does not reproduce: lost-response retries and MCP process restarts deliver equal command bodies, including equal keys, tool-call IDs and injected revisions. Separate intentional IDs remain different operations. Forged lifecycle fields are sanitized, conflicting identity/input combinations refuse, concurrent identical retries retain one envelope, late receipts do not revert the revision, and definite request errors permit correction. Existing read calls, agent-visible error results and client auth/refusal behavior remain covered.

Ordered gates on the final affected working-tree state:

- Syntax/import/type: `uv run --no-sync ty check src dev docs scripts packaging` passed; focused Ruff lint and formatting passed on the changed Python files and MCP package; `git diff --check` passed on the assigned patch.
- Security trigger and alternate inputs: `uv run --no-sync python -m pytest src/vaultspec_a2a/authoring/tests/test_dispatch_injection.py src/vaultspec_a2a/authoring/tests/test_catalog_unit.py src/vaultspec_a2a/authoring/tests/test_client_unit.py src/vaultspec_a2a/authoring/tests/test_client_reresolve.py src/vaultspec_a2a/protocols/mcp/tests src/vaultspec_a2a/providers/tests/test_acp_authoring.py src/vaultspec_a2a/worker/tests/test_authoring_binding.py src/vaultspec_a2a/control/tests/test_storage_paths.py src/vaultspec_a2a/control/tests/test_state_seal.py` passed: 172 tests, two service tests deselected by the repository default marker policy.
- Legitimate behavior and platform: the same suite covers separate intentional calls, reads, auth failures, lifecycle injection, provider configuration handoff and state paths. A real Windows stdio process restart passed. `docker run --rm --entrypoint /app/.venv/bin/python ... vaultspec-worker-s06 /proof/artifacts/linux_authoring_replay.py` passed against image `sha256:4ee1d3e8c92120ad22c204dea2bab0760eaace8df2415ad51c229622a5fb9e84` with the current source mounted read-only, explicit UID/GID configuration and a real loopback HTTP contract server. Exact mount/environment arguments and the retained helper are in the target-bound security evidence collection.

The external dashboard engine and real model provider turn were not exercised. The local tests establish the dispatched identity/envelope invariant through real HTTP/MCP boundaries; the engine remains the authority that deduplicates equal keys. No upstream finding status was changed and no push was requested.

## Recommendations

Provider integration should own the stable native call-identity proof before advertising mutation capability on those adapters. Runtime lifecycle should decide the journal retention window against terminal-run and reconnect guarantees. Authoring integration should wire and verify stdio bearer refresh independently. Keep the accepted engine boundary and token discipline unchanged.
