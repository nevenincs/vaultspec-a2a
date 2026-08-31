---
tags:
  - "#adr"
  - "#provider-model-catalog"
date: '2026-08-02'
related:
  - "[[2026-08-02-provider-model-catalog-research]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
  - "[[2026-07-15-model-profiles-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
supersedes:
  - '2026-07-15-model-profiles-adr'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:482ca2aa625a5e87873cfa2df1b57c7456e25bbc4d6de68678a93149405f4835'
---
# `provider-model-catalog` adr: `provider-owned model catalogs, bounded run selection, and truthful provider health` | (**status:** `accepted`)

## Problem Statement

A2A and Dashboard need one truthful contract for letting users decide which
provider, model, and provider-supported controls produce each artifact. The
accepted model-profile decision keeps policy in static server profiles and
forbids direct selection, while the Dashboard product decision requires
provider-free teams and user selection at run start. This record replaces the
profile-only ownership rule while preserving deterministic execution,
restart/replay stability, and completed-turn admission. Grounding is in
`2026-08-02-provider-model-catalog-research` and
`2026-08-02-provider-model-catalog-reference`.

## Considerations

- Provider, model, and native controls are separate facts; model enumeration
  does not establish a universal low/medium/high taxonomy.
- A product run must explicitly bind served selections; omission may not
  silently choose the artifact producer.
- The existing per-role frozen assignment is the durable restart boundary.
- Configuration, installation, authentication, catalog freshness, and
  completed-turn admission are independent health facts.
- Discovery belongs in the provider descriptor/registry accepted by
  `2026-02-25-llm-context-provider-abstraction-adr`; LangChain remains
  downstream invocation machinery.
- A fallback is an explicit user-visible execution selection, never an
  unannounced substitution.

## Considered options

- **Retain named profiles and improve health.** Rejected: preserves static
  ownership and contradicts provider-free product teams.
- **Accept provider and model strings directly.** Rejected: callers could name
  unavailable models and bypass account-specific validation.
- **Infer universal model tiers.** Rejected: provider semantics are not
  equivalent, so name-based normalization would fabricate policy.
- **Serve provider-owned catalogs and accept only served references.** Chosen:
  direct choice remains bounded, provenance-carrying, and fail-closed.
- **Whole-team-only choice.** Rejected: insufficient for heterogeneous artifact
  roles.
- **Unbounded per-role maps.** Rejected: bounded overrides over one served
  whole-team selection supply expert control without arbitrary input.

## Constraints

- Production source, team TOML, and Dashboard code contain no concrete external
  model identifiers or centrally maintained model-tier mappings.
- An execution lane exposes only choices advertised by that same lane; an API
  catalog cannot authorize a CLI/ACP model.
- Missing enumeration remains `catalog_available=false`; no compatibility list
  or guessed tier fills the gap.
- Every selectable external lane retains completed-turn admission.
- ACP discovery ends before prompt, reaps the subprocess, and discloses no
  credentials.
- Stale catalogs are visible but unselectable until refreshed or revalidated.
- New runs revalidate current membership; existing runs restart from frozen
  exact values even after catalog drift.
- Same-id replay compares the canonical selection fingerprint and does not
  require the old entry to remain in a current catalog.
- Internal deterministic test lanes stay hidden and may remain fixture-pinned.

## Implementation

**Provider registry and catalog.** A2A owns a normalized catalog service backed
by execution-mode-specific provider adapters. Provider records expose identity,
display metadata, structured health, catalog state/revision/freshness, model
entries, native controls, and bounded reasons. Model and control identifiers are
opaque provider-issued values addressed through server-local catalog entries.

**Provider adapters.** Generic ACP consumes session configuration options;
Gemini also supports its advertised session model shape. Codex app-server uses
model, capability, and account RPCs. Kimi uses the installed CLI's configured
provider/model surfaces and supported ACP/launch arguments. OpenAI-compatible
API lanes use authenticated model-list endpoints only where verified. Z.AI's
catalog comes from its configured lane rather than Claude adapter aliases.

**Selection contract.** Product presets retain topology, personas, tools, and
role requirements but no provider/model policy. Run start carries one required
whole-team served selection, optional bounded per-role overrides, optional
explicit served fallbacks, and provider-native control values. Each reference
includes provider, execution mode, catalog revision, entry id, and bounded
controls. Dashboard sends only values served by A2A.

**Health.** A2A separately serves configured state, transport state,
authentication state, catalog state, completed-turn admission, derived
selectability, safe reasons, and timestamps. Credential presence proves only
configuration; a no-completion provider probe proves authentication/catalog
access; only a completed real turn proves admission.

**Freeze and replay.** Before durable creation, A2A revalidates and freezes per
role the provider/execution mode, catalog revision and entry, exact model value,
controls, fallbacks, provenance, and selection schema. The digest covers the
complete selection. Compiler and factory consume only frozen values. Legacy
frozen profile metadata remains readable solely to restart existing runs.

**Retirement.** Product model profiles, static `MODEL_MAP`, implicit provider
defaults, and provider-bearing team configuration are removed from new-run
policy. Dashboard replaces its profile picker with provider, model, and native
control selection and displays authoritative frozen assignments after start.

## Rationale

Provider-owned, execution-mode-specific catalogs are the only option satisfying
direct user choice, bounded validation, no hard-coded models, and honest
absence. Bounded whole-team selection plus per-role overrides supports both the
simple composer and expert agent-panel use case. Extending the existing frozen
assignment preserves the strongest part of the old profile architecture while
removing its invalid static ownership assumption.

## Consequences

- Users explicitly choose what produces artifacts globally or per role.
- Sol, Fable, and future models appear without repository releases only when
  their active provider lane advertises them.
- Provider-native effort and service controls remain truthful and overrideable.
- Catalogs can vary by account, authentication, region, CLI version, and
  execution mode without hard-coded updates.
- Some configured providers remain visible but unselectable when enumeration or
  completed-turn proof is absent.
- Refresh introduces bounded subprocess/network work, expiry, concurrency, and
  error-handling obligations.
- Legacy runs remain restartable, while legacy profiles cannot start new product
  runs.
- On acceptance this record supersedes the profile-only ownership decision in
  `2026-07-15-model-profiles-adr` while preserving its freeze and admission
  invariants.

## Amendment (2026-08-03): run-start response disclosure and mandatory metadata

Decided while migrating the run-start callers to the explicit-selection
contract; codifies the response-side consequences of the Selection contract
above.

- **One start-surface authority.** The run-start and run-commit responses
  disclose exactly one execution authority: the frozen team assignment. The
  retired profile pair - `profile_id` and the top-level `assignments` list -
  is removed from those responses rather than served empty. The request
  schema refuses every profile-driven body, so on a success those fields
  could only report a confident emptiness a client cannot distinguish from
  "no assignments exist".
- **Legacy disclosure narrows to the read surfaces.** Run-status retains
  `profile_id` and per-role `assignments`, because runs frozen before this
  record remain readable and restartable there. Per-role provider readiness
  stays a live host fact: probed at read time by the preset listing and by
  the legacy run-status disclosure, never persisted inside a freeze.
- **Every run has metadata; every run is named.** A selection revalidates
  against the catalog served for its workspace and the workspace rides in
  run metadata, so a run without a metadata envelope is refused before
  anything durable exists. The gateway therefore names every run - the
  caller's nickname when supplied, a minted one otherwise. Null metadata and
  null nicknames are legacy-row states, not producible ones.
