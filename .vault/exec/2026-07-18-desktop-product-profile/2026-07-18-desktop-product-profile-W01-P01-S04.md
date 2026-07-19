---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S04'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Disable runtime uvx acquisition in the desktop profile and return an actionable unavailable capability result

## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py`

## Description

- Add an explicit typed desktop versus non-desktop harness MCP resolution authority.
- Return stable path-free unavailable-capability detail for desktop RAG acquisition.
- Filter unavailable desktop capabilities from ACP, Codex, config-home, and allowlist serialization.
- Scrub stale unavailable launch and allowlist entries during desktop composition.
- Inspect pre-attached desktop state even when the current harness declaration is empty.
- Preserve existing Compose and foreground-development resolution through the non-desktop default.
- Prove the boundary with direct production imports and real model objects.

## Outcome

`HarnessMcpRuntimeProfile` now makes capability resolution policy an explicit
typed input. `resolve_harness_mcp_capabilities` requires the caller to select
that profile and never derives it from the working directory, environment, or
executable search path. Under `DESKTOP`, the registry's runtime-acquired
`vaultspec-rag` server produces one `capability_unavailable` result with the
path-free reason `runtime acquisition is disabled for the desktop profile` and
the action `Install the separately packaged vaultspec-rag desktop capability,
then retry.` No `uvx` command, argument, executable path, or tool allowlist is
present in that result.

The ACP launch-spec resolver, autonomous allowlist resolver, Claude and project
config-home selector, Codex config selector, and model composition seam now all
accept the typed profile. Their existing default is `NON_DESKTOP`, so current
Compose and foreground-development callers retain the published uvx behavior.
Explicit desktop resolution emits no launch or allowlist material. Desktop
composition also removes a stale `vaultspec-rag` launch spec and its qualified
tool names while preserving an unrelated authoring bridge; the Codex lane
clears its harness declaration before it can build `config.toml`. Desktop
registry admission is deny-by-default: only an entry explicitly marked
desktop-available and explicitly marked as not using runtime acquisition can
cross those serializers. Contradictory `true` and `true` markers and omitted
acquisition metadata are both unavailable.

Desktop composition also inspects pre-attached ACP and Codex state when the
current declaration list is empty. A stale ACP uvx spec and its allowlist or a
stale Codex `vaultspec-rag` declaration is removed before serialization. The
non-desktop empty-declaration path still returns the original model object
without mutation or copying.

Nine new real-behavior tests in
`src/vaultspec_a2a/providers/tests/test_acp_mcp_desktop_profile.py` import the
production resolver and real `AcpChatModel`, `CodexChatModel`, and live team
preset. They prove the exact unavailable result, every serialization boundary,
contradictory and omitted registry metadata, stale-entry removal with declared
and empty inputs, and unchanged non-desktop behavior. All nine passed. The
58 impacted provider and config-home regressions also passed. Ruff formatting
and linting passed for the changed and directly impacted source, and scoped ty
checking passed for both changed files.

## Notes

Architecture integration remains deliberately blocked on `W02.P04.S16`.
No authoritative desktop profile exists yet, so no current application call
site selects `HarnessMcpRuntimeProfile.DESKTOP`. S16 must carry that explicit
authority into harness resolution and surface the returned unavailable result.
This step establishes and verifies the fail-closed resolution and serialization
seam; it does not claim end-to-end desktop runtime closure.

Independent code review found no critical or high-severity issue. Its one
medium finding identified that omitted future registry classification could
fail open; explicit deny-by-default desktop admission resolved that finding and
the focused and impacted suites passed again. Its low finding identified an
obsolete add-only composition docstring; the contract now distinguishes
non-desktop addition from desktop scrubbing. Re-review passed with no remaining
finding.

A subsequent independent review required two further revisions. Its high
finding required both explicit desktop availability and explicit
`runtime_acquisition is False`; its medium finding showed that the empty-name
fast path retained pre-attached ACP and Codex RAG state. Both are resolved with
real-model regressions, and the focused and impacted suites pass. Follow-up
review remains the next gate.

Repository-wide ty checking reached five pre-existing diagnostics in unrelated
graph and provider test helpers. None touches the two S04 files; their scoped ty
check is clean. The S04 plan row remains open for architecture review, and no
commit was created.
