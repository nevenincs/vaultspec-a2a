---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8c86b5812606eb51a683dffcef7e02481a76f4c0341e6c4de84de0ee6dec94e6'
step_id: 'S05'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Capture a live ZAI error payload and record the discriminator fidelity verdict

## Scope

- `src/vaultspec_a2a/providers/tests/test_zai_error_fidelity_live.py`
- `src/vaultspec_a2a/providers/tests/_installed_vocabulary.py`

## Description

- Add a service-marked live probe that provokes a real failure on the Z.ai lane
  by swapping only the bearer token for a deliberately invalid one, leaving the
  command, backend, gateway URL and session setup on the production path.
- Assert the raised prompt error carries a structured `errorKind`, that the kind
  is a member of the vocabulary read from the INSTALLED agent SDK type
  declaration, and that a rejected credential types as `authentication_failed`.
- Add a shared reader that parses the `SDKAssistantMessageError` union out of the
  installed SDK declaration, so no test states that vocabulary itself; a member
  added upstream surfaces as an unmapped kind rather than passing unnoticed.
- Raise a `MissingInstalledVocabularyError` when the installed declaration is
  absent or has moved, so the caller skips naming the missing prerequisite
  instead of asserting over an empty set.
- Skip with the missing prerequisite named when no Z.ai token is configured, so
  an unarmed lane is reported unproven rather than proven.

## Outcome

The verdict is affirmative and observed, not inferred. A real rejected credential
against the real Z.ai Anthropic-compatible gateway, driven through the real
adapter, produced:

`code = -32603`, `data = {'errorKind': 'authentication_failed'}`, message
`ACP prompt failed: {'code': -32603, 'message': 'Internal error: Failed to
authenticate. API Error: 401 token expired or incorrect', ...}`

Two things make this evidence rather than shape-checking. The gateway's own prose
is `token expired or incorrect`, which is NOT Anthropic's wording, and the CLI
still typed it correctly - so the classification did not come from prose
matching. And the value arrived on the documented channel: the adapter's
internal-error frame with the kind in `data`.

The governing decision gated this lane's typing on live evidence because the CLI
derives some kinds by matching Anthropic's English error text. The binary's
authentication branch that fired here is gated on the response STATUS, not on the
message, which is why it survived a foreign gateway. The verdict is therefore
bounded rather than blanket: status-gated kinds hold on this lane and the shared
ACP mapping may serve both lanes for them. Message-gated kinds - the
organization-policy refusal and the api-key-disabled branches, each of which
requires a literal Anthropic sentence - remain UNOBSERVED here, and this lane
should be expected to fall through to a coarser kind for them. That is safe
under a total mapping whose floor is the unknown member, and it is the reason the
mapping must not raise on an unrecognised discriminator.

The vocabulary itself was also checked against the shipped CLI binary rather than
only the type declaration, and the two agree on ten members. An earlier reading
that suggested an eleventh member was a misread: that literal is a UI state
value in a remediation-hint table keyed BY error kind, not a kind.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly` over the whole providers test package: 600 passed, 2
failed, 30 deselected - both failures pre-existing and unrelated, recorded below.
The live probe itself passed in 233s under
`pytest -m service --timeout=700 --timeout-method=thread`.

## Notes

The probe is slow by nature and its bound was corrected after a first run failed.
An authentication status is RETRYABLE in the CLI's own retry table, so a rejected
credential is not a fast failure: the CLI exhausts its backoff schedule first,
taking 232s and 233s on two independent runs. The first bound of 180s cut the
turn off mid-retry and reported a timeout; it now sits at 480s, comfortably above
the observed duration and comfortably below the turn idle deadline, so a genuine
hang still fails rather than parks. This is worth carrying forward: any live
failure probe on this lane costs about four minutes of wall clock, and a lane
retry hint would be the honest thing to prefer over inferring retryability from
the condition here.

Two pre-existing failures in `src/vaultspec_a2a/providers/tests/test_acp_mcp_desktop_profile.py`
are unrelated to this Step and were left alone. Both assert
`_build_codex_config_home()` returns `None` for an empty declaration, but the
production method now ALWAYS emits a worker-owned config home - deliberately, so
that an otherwise tool-free turn cannot inherit the operator's ambient MCP
servers. The test encodes the superseded contract. Neither the production module
nor the test file is in this Phase's scope, and a concurrent writer is active in
the same tree, so this is recorded as a finding rather than fixed here.

A divergence noted for a later Step rather than acted on: the repository's
`is_auth_required_error` predicate matches the numeric authentication code or
four message substrings, none of which is the `authentication_failed` kind the
adapter actually sends on its internal-error path. The kind observed live here
would therefore not be recognised as an authentication requirement by that
predicate. The condition mapping added in the following Steps does recognise it;
reconciling the older predicate is out of this Phase's scope.

The workspace is shared with a concurrent writer who staged unrelated provider
catalog files mid-Step. This Step's commit named its paths explicitly and took
none of them.
