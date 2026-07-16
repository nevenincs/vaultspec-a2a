---
tags:
  - '#audit'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
  - "[[2026-07-15-graph-agent-framework-harness-adr]]"
---
# `graph-agent-framework-harness` audit: `batch-2 and batch-3 reviewer verdict: bundled rule wiring, role-leak fix, and context-graph cycle break`

## Scope

Reviewer-persona verdict covering two commit batches on the
`graph-agent-framework-harness` feature: the bundled document-authoring rule
mechanism and its wiring into worker/supervisor turns (batch 2), and the
context-graph import cycle fix that retroactively closes a batch-2 caveat
(batch 3). Batch 2 commits: `e975850` (bundled-read mechanism),
`96bd13e` (wiring into worker/supervisor turns), `76eb559` (HIGH-1 fix),
`138f76f` (researcher parity fix). Batch 3 commits: `85cb993` (import-cycle
break), `6e38e0e` (sole-writer invariant comment). The value of this record
is the full REVISION REQUIRED -> fix -> PASS arc, not just the final state.

## Findings

### batch2-e975850 | low | bundled-read mechanism, PASS with two open caveats

**PASS** on `e975850` (bundled document-authoring rule defaults + the
workspace-override read). Two non-blocking findings carried forward:

- **LOW-3** - the mechanism declares an `order:` key on bundled rule sources
  but nothing downstream consumes it; bundled rules load in whatever order
  the directory read returns them, not the declared order. A fix is in
  flight.
- **LOW-4** - two cache-invalidation gaps in the bundled-read path lack test
  coverage. Non-blocking; recorded open, not fixed in this batch.

### batch2-96bd13e | high | REVISION REQUIRED - bundled conventions leaked into every whole-corpus turn

`96bd13e` (wiring role-scoped bundled rules into the worker/supervisor
turns) shipped **HIGH-1**, verified live rather than by inspection alone:
document-authoring bundled rule conventions were appearing in every
coder/supervisor turn, not just document-authoring turns. Root cause was
two-fold: the bundled rules directory was read unconditionally regardless of
the active role, and the role filter itself was disabled because the
compiled rule set was built via `compile(None)` at this call site, which
never engages role-scoping logic in the first place. The test-design lesson
recorded here: the existing tests asserted only that the expected bundled
content was *present* in a document-authoring turn ("present" assertions) —
none asserted its *absence* from a non-authoring turn, so a full cross-role
leak still passed every test green. **Verdict at this point in the arc:
REVISION REQUIRED**, not PASS.

### batch2-fix | high | HIGH-1 fixed and independently verified

Fixed by `76eb559` (bundled directory read gated on
`_DOCUMENT_AUTHORING_ROLES`; the supervisor turn reverted to workspace-only
rules; a negative assertion added proving bundled content is now absent from
non-authoring turns) plus `138f76f` (extends the same gating to the
researcher persona for parity, with the role hardcoded at that call site so
there is no `None`-role branch left to fall through). **FINAL PASS** on the
wiring: all three production `RuleManager` call sites (worker, supervisor,
researcher) were individually enumerated and verified to gate bundled
document-authoring content on role, with the negative (absence) assertion
now present alongside the positive one.

### batch3-85cb993-and-6e38e0e | low | cycle break and invariant comment, clean PASS

**PASS**, no findings. `85cb993` breaks the `context` <-> `graph` package
import cycle using PEP 562 module-level lazy `__getattr__` initialization,
with the subprocess-isolation boundary pinned so the lazy init cannot
straddle a process fork mid-initialization. This retroactively resolves the
batch-1 audit's collection caveat (`2026-07-16-adr-authoring-orchestration-batch1-recovery-race-review-audit`
LOW-1): `6e38e0e` lands the sole-writer invariant as a code comment at its
enforcement point, exactly the fix that audit recorded as "in flight."

## Recommendations

- Land LOW-3 (`order:` key consumption) when convenient; non-blocking.
- Track LOW-4's two cache-invalidation coverage gaps as follow-up test debt;
  non-blocking, does not gate this feature's close.
- Carry the negative-assertion lesson from HIGH-1 forward as a standing
  review habit: any role-scoped or conditionally-bundled content needs a
  test asserting absence in the excluded case, not only presence in the
  included case.
- No further action needed on `e975850`/`96bd13e`/`76eb559`/`138f76f`/
  `85cb993`/`6e38e0e`; the wiring and cycle-break work is closed.
