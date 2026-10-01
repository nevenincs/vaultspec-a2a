---
tags:
  - "#adr"
  - "#langgraph-conformance"
date: '2026-10-01'
related:
  - "[[2026-10-01-langgraph-conformance-core-reader-parity-adr]]"
  - "[[2026-09-30-langgraph-conformance-audit]]"
  - "[[2026-07-16-authoring-contract-adr]]"
supersedes:
  - '2026-10-01-langgraph-conformance-core-reader-parity-adr'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:ccc8388bc1b7bf14a06a1234fd8a1d9ada5a08cfd709ce917cda921b1f3640bd'
---
# `langgraph-conformance` adr: `core runtime dependency` | (**status:** `accepted`)

## Problem Statement

This runtime enforces several of vaultspec-core's rules at a different moment than core does: the authoring submitter refuses a document before it is written for the body-link violations core refuses after it lands, and the rules loader reads rule frontmatter in the format core owns. Each enforcement point carried its own copy of core's reading. `2026-10-01-langgraph-conformance-core-reader-parity-adr` chose to keep that shape with a port held to core by a parity test. The user reversed that choice the same day: a copy that a test chases is still a copy, and core is the framework this service exists to serve.

## Considerations

- Core's reading is public API: `vaultspec_core.vaultcore.parser` exports `split_frontmatter`, `parse_frontmatter` and `parse_vault_metadata`, and `vaultspec_core.vaultcore.checks` exports `check_body_links` over an in-memory `VaultSnapshot`.
- Core's runtime requirements beyond what this package already ships are networkx, phart, ruamel-yaml, rustworkx and typer; the frozen binary already bundles core (`pyproject.toml`, the `freeze` group).
- The ADR grounding vocabulary has no importable name in core, so it stays a value held to core's source by `src/vaultspec_a2a/authoring/tests/test_core_grounding_parity.py`.

## Considered options

- Runtime dependency, core's own functions called directly (chosen). No copy exists to drift.
- Port held by a parity test (`2026-10-01-langgraph-conformance-core-reader-parity-adr`). Superseded: the copy remains and is maintained on core's release schedule.
- Shell out to the core CLI. Rejected: a process per submit on the turn path for what is a pure function call.

## Constraints

- `vaultspec-core` is a `[project]` dependency with a floor and no upper bound, matching the user's standing instruction for the framework packages.
- Where core exports the reading or the check, this package calls it and keeps no copy. Notes a writer receives for a body-link violation are core's own diagnostics.
- A core value with no importable name may be held as a constant only with a test that reads it from the installed core and fails, never skips, when it cannot.

## Implementation

We will declare vaultspec-core a runtime dependency, run core's `check_body_links` over a one-document snapshot built with `parse_vault_metadata` in the authoring submitter, split frontmatter with `split_frontmatter`, read rule frontmatter in `src/vaultspec_a2a/context/rules.py` with `parse_frontmatter` and `split_frontmatter`, and delete the port `src/vaultspec_a2a/authoring/_prose.py` with its parity test.

## Rationale

Calling core removes the drift instead of detecting it, costs no process and no network, and the added runtime packages are small next to the closure the service already carries. The service is core's runtime partner; depending on it is the honest shape of that relationship.

## Consequences

- A core release that changes its reading changes this service's refusals in the same lock bump, with no port to update.
- The wheel's runtime closure grows by core and its five additional requirements.
- Core's public API becomes a compatibility surface for this package; a breaking change there fails this package's tests on the bump.

Authorization: proposed by the user on 2026-10-01 ("a2a could make core a direct dependency (not a dev dependency but a project dependency) so that ports are not needed"; confirmed "yes! exactly, instead of the port"), accepted under the user's blanket approval of that date.
