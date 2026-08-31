---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:caab326ba9fd68a26c053cb76f16f8daf722d1ce9a4f157e7b3f4dbd697aa311'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `run-start disclosure decisions and migration findings`

## Scope

The open contract questions left by the explicit-catalog-selection change to
run-start: the empty top-level assignments disclosure, the now-unreachable
metadata-less run state, universal auto-nicknaming, the invalid-workspace
refusal test shape, and the seven remaining live-gateway suite failures. Each
question was decided and implemented in this pass; the decisions themselves are
recorded in the 2026-08-03 amendment of the governing decision record. This
document classifies what the work surfaced.

## Findings

### start-surface-legacy-pair | medium | run-start and run-commit served a structurally empty legacy disclosure

The start and commit responses carried the retired pair (a null profile id and
an empty top-level assignments list) on every reachable success, since the
request schema refuses every profile-driven body. A client could not
distinguish "no assignments" from "look at the freeze". RESOLVED: the pair is
removed from both responses in `src/vaultspec_a2a/api/schemas/gateway.py` and
`src/vaultspec_a2a/api/routes/gateway.py`; the frozen assignment is the single
start-surface authority. Run-status retains both shapes for runs frozen before
the catalog contract.

### migration-shared-run-id | high | a migrated helper posted two intentions under one run id

The permission-scoping live test's start helper hard-coded one run id and was
called twice, so the second start became a changed-body replay the gateway
rightly refuses with 409 - the suite failure was manufactured by the
migration, not the contract. RESOLVED: each start now carries its own id. The
same shape - one syntactic post serving several runtime requests - is a
standing migration hazard.

### migration-metadata-clobber | high | spreading the shared selection helper overwrote a test's own metadata

In the modern-selection nickname-collision race, spreading the shared
run-fields helper after the test's own payload replaced the metadata envelope
carrying the deliberately shared nickname, dissolving the collision under
test into two auto-named runs (201/201 where 201/409 is the contract).
RESOLVED: the helper is no longer spread over an explicit metadata envelope.
Any test that declares its own metadata must not compose it with the helper's.

### cold-workspace-catalog-latency | low | a fresh workspace pays its first catalog build inside the run-start request

Selection revalidation resolves the catalog served for the run's workspace;
for a workspace never seen before, that first build takes tens of seconds
locally (subprocess and lane probing), which a caller pays inside the
run-start request budget. Two live tests siting runs in fresh temporary
directories timed out on exactly this and were resited into the shared
workspace. Operationally, a dashboard starting a run in a brand-new project
may see a slow or timed-out first start unless it warms the catalog through
the catalog read first.

### unmigrated-legacy-consumers | medium | four suites still speak the retired profile contract

Still posting the forbidden profile field or reading the removed top-level
assignments from start responses: `api/tests/test_model_profiles_evidence.py`
(whole file pins the retired contract),
`acceptance/tests/test_dashboard_contract.py` (asserts a truthy profile id on
the certified start surface), `service_tests/test_dispatch_assignment_agreement.py`
(reads top-level assignments), and `service_tests/test_clarification_loop_stitched.py`
(posts a profile id). All were failing before this pass for request-side
reasons; the response-side removal makes their retirement final rather than
newly breaking them. They belong to the ongoing caller-migration effort.

## Recommendations

- Migrate or retire the four suites above as part of the caller migration;
  the acceptance dashboard-contract case additionally needs the cross-repo
  edge re-certified against the frozen-assignment disclosure.
- Consider a catalog warm-up path (or a documented pre-read) for first runs
  in a fresh workspace, so the first start does not absorb the cold build.
