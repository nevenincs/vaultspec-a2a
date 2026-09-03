---
tags:
  - '#audit'
  - '#provider-capability-evidence'
date: '2026-08-02'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:71efa625adbc554d5202df59f1a97df1f031a0d009a498572a07de940d76b6ba'
related:
  - "[[2026-08-02-provider-capability-evidence-plan]]"
---
# `provider-capability-evidence` audit: `capability contract p01s01 review`

## Scope

A real code review of `src/vaultspec_a2a/providers/provider_capabilities.py`
against `[[2026-08-02-provider-capability-evidence-adr]]`'s Constraints and
Implementation sections and against
`[[2026-08-02-provider-capability-evidence-plan]]`'s `P01.S01` row. Reviewed:
the `__post_init__` invariants on `CapabilityBlock`, `CapabilityProof`,
`CapabilityEvidence`, and `CapabilityMatrix`; the derived `status` property's
correctness against every combination of support, proof, and blocker facts;
immutability and aliasing under `frozen(slots=True)`; the matrix completeness
check; error-message quality; and the module's own tests
(`src/vaultspec_a2a/providers/tests/test_provider_capabilities.py`, 7 cases,
run and confirmed passing on 2026-08-05, alongside a clean `ruff check` and
`ty check`). Out of scope: `P01.S02`'s derivation from real catalog,
admission, web, and permission sources, and `P02`'s provider population and
proofs - neither exists in this module yet.

## Findings

1. **MEDIUM - contract fidelity - OPEN.** `CapabilityEvidence.__post_init__`
   explicitly rejects a `proof` on an unsupported record ("an unsupported
   capability cannot carry a proof") but has no equivalent guard for
   `blockers`. Verified live: constructing
   `CapabilityEvidence(upstream_supported=False, blockers=(CapabilityBlock(...),), ...)`
   succeeds without error. `status` still resolves correctly to `UNSUPPORTED`
   (the `not self.upstream_supported` branch is checked first), so no
   misreporting reaches a consumer of `status` today - but the stored
   `blockers` become dead data no reader should trust, and it is an
   asymmetry against the module's own docstring for `CapabilityBlocker`
   ("Bounded causes that can presently block otherwise supported behavior"):
   an unsupported capability has nothing "otherwise supported" left to
   block.

2. **LOW - robustness - OPEN.** `CapabilityMatrix.record()` resolves via a
   bare `next(record for record in self.records if record.capability is capability)`
   with no default. A query for a capability absent from `records` raises
   the built-in `StopIteration` rather than a message naming the missing
   capability. Unreachable under type-correct input today, because
   `__post_init__` already guarantees every `Capability` member is present
   exactly once - but the failure mode, if that invariant were ever
   relaxed or a caller mutated a stale reference, is an unannounced
   iteration-protocol exception rather than a diagnosable error.

3. **LOW / clean - correctness - confirmed, no defect.** The derived
   `status` property orders its checks unsupported, then blocked, then
   proven, then supported_unproven. A lane carrying both a historical
   `CapabilityProof` and a current `CapabilityBlock` therefore reports
   `BLOCKED`, never `PROVEN` -
   `test_blocked_evidence_retains_support_and_historical_proof` pins exactly
   this case. This is the mechanism that truthfully represents a
   credential-blocked-but-previously-proven lane, the concrete state the
   ADR's Problem Statement identifies as missing a truthful surface. No
   false-green path was found in the status derivation.

4. **LOW / clean - immutability and aliasing - confirmed, no defect.** Both
   `CapabilityEvidence.blockers` and `CapabilityMatrix.records` are
   re-wrapped with `tuple(...)` via `object.__setattr__` inside
   `__post_init__` - the standard idiom for defending a
   `frozen(slots=True)` dataclass against a caller passing a mutable list
   that could be mutated after construction. No path was found where a
   caller-held list alias could later change an "immutable" record's
   contents.

5. **LOW / clean - contract fidelity - confirmed, no defect.** The
   identity-transfer guards the ADR's Constraints require are present and
   tested: `CapabilityProof.key` and `.capability` must match the owning
   evidence record's own lane and capability exactly
   (`test_proof_requires_its_exact_lane_and_capability`), and
   `CapabilityMatrix` rejects any record whose `key` differs from the
   matrix's own lane (`test_matrix_rejects_missing_duplicate_or_cross_lane_records`).
   No path was found for evidence to transfer across provider, backend, or
   execution mode through this module.

6. **LOW / clean - completeness - confirmed, no defect.** `CapabilityMatrix.__post_init__`
   requires exactly one record per `Capability` member (a length check plus
   a set-equality check against `set(Capability)`), matching the ADR's
   "every external lane carries every matrix capability, and the capability
   set is immutable and complete." Tested for both a missing and a
   duplicated capability in `test_matrix_rejects_missing_duplicate_or_cross_lane_records`.

7. **LOW / clean - error-message quality - confirmed, no defect.** Every
   raised `ValueError` names the offending field or invariant in plain
   language ("an unsupported capability cannot carry a proof",
   "permission_mode requires a permission_reason",
   "capability blockers must not repeat a kind"); none echo raw external
   payloads or leak anything beyond the already-bounded, already-validated
   text fields the module itself accepts.

8. **Scope observation - test coverage exists, is narrow.**
   `src/vaultspec_a2a/providers/tests/test_provider_capabilities.py` holds
   seven direct contract tests exercising every dataclass in this module
   and both of its rejection paths. Confirmed by running
   `pytest src/vaultspec_a2a/providers/tests/test_provider_capabilities.py -v`
   on 2026-08-05: 7 passed in 0.09s. This is contract-only coverage; it does
   not and cannot yet exercise `P01.S02`'s derivation from real catalog,
   admission, web-proof, or permission-policy sources, because that
   derivation code does not exist in the tree yet.

## Recommendations

1. **Addresses Finding 1 (MEDIUM).** Add a `__post_init__` guard on
   `CapabilityEvidence` rejecting a non-empty `blockers` tuple when
   `upstream_supported` is `False`, mirroring the existing proof guard -
   for example
   `if not self.upstream_supported and self.blockers: raise ValueError("an unsupported capability cannot carry a blocker")`.
2. **Addresses Finding 2 (LOW).** Replace the bare `next()` in
   `CapabilityMatrix.record()` with a form that raises a named,
   capability-identifying error (or accepts an explicit default) instead of
   relying on `StopIteration`, so a future relaxation of the completeness
   invariant fails with a diagnosable message rather than a bare iteration
   error.
3. Resolve Finding 1 before this Step is marked complete on the plan; `P01.S02`'s
   derivation logic should not need to rely on the module accepting an
   unsupported-plus-blocked combination, but nothing currently stops it from
   doing so by accident.
4. No finding here blocks `P01.S02` from building on the current contract
   types; the derivation phase can proceed once Finding 1 is closed.
