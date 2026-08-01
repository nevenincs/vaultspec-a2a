---
tags:
  - '#exec'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:691bd9d814e44ef8923b6693aca10f325efcc90e0e88d2a3ce3b8f52f6b0cd66'
related:
  - "[[2026-08-01-tool-cores-plan]]"
---
# `tool-cores` P01 summary

## Scope

The three contract seams outbound grounding depends on: network egress as its
own declared trust axis on the harness registry, the typed web locator admitted
into the research-finding contract, and a submit refusal that will not let a
document hide the retrievals its run performed.

The capability stays dark for the whole Phase by design. Nothing composes a web
tool, no persona claims online access, and no configuration enables search. The
activation gate is a later Step, so these seams land as contract only.

## Outcome

All three Steps landed and the Phase passed formal review with no critical or
high finding. Five implementation commits, three Step Records, one review.

The egress axis is enforced at two depths. A registry construction seam refuses
any entry omitting either trust axis, which makes an undeclared entry
unconstructible rather than merely unsurfaceable; the composition seams keep a
matching assertion as redundancy. The native tool set carries the same axis,
where membership is the declaration, and that half fires at the real spawn path
against a genuinely undeclared name.

The locator contract admits a bare string for internal locators unchanged, or a
typed dictionary for a web locator, validated on the real branch path. Its
acceptance was the checkpoint round-trip, proven through a saver reopened on the
same file after the first connection closed, with the harness itself probed to
confirm the assertion could fail.

The submit refusal reuses the existing conformance error and revision routing
rather than adding a second mechanism, scans the prose region so a URL hidden in
frontmatter cannot discharge the obligation, and is scoped to research
documents. Its acceptance was a mutation run, and one mutation was more
informative than its pass count: with the check absent the run reaches the
network instead of refusing, which proves the refusal precedes engine contact
rather than merely that an assertion was missing.

## Findings

Four medium findings carried forward, two of which are one decision seen from
two sides, and both now assigned to a new delivery-Phase Step.

The typed channel has no production emitter: the research producer returns an
empty locator list unconditionally, so the contract admits a shape nothing
produces and the refusal cannot fire in a real run. Separately, branch-side
validation raises out of a node wired with no retry policy, unlike every sibling
in the topology, so once an extractor lands a deterministic validation failure
would abort the run rather than route into revision. Deciding whether the
producer clamps or the branch refuses resolves both, and the later live-proof
Step cannot pass without it.

The remaining two are recorded rather than actioned. The registry's fail-loud
trust assertions cannot be reached by any legitimate production input, and that
property predates this work - the pre-existing read-only guard has it too. And
the submit refusal is now narrower than the record that governs it, which is a
drift the record must close rather than the code reverting.

## Notes

The Phase's most useful result was a correction to its own reasoning. The
research-only scoping was justified partly on the claim that a later document
had nowhere sanctioned to put a URL and so could not comply. Review disproved
it: a bare URL in prose is refused by nothing, because the markdown-link check
deliberately exempts web targets. The scoping stands on the one-home convention
alone. Code comment, Step Record, and audit were corrected, and the audit notes
the overstatement was authored here rather than inherited - a wrong reason
recorded confidently being the same defect class this feature exists to close.

Two findings surfaced that belong to neither this Phase nor this feature and are
recorded so they are not rediscovered as fallout: two authoring discovery tests
fail on any host running a live engine, where a sibling test in the same file
carries the hedge they lack; and a parallel session's in-flight lane-admission
work accounts for the type diagnostic and test failures every executor reported
around. Neither was touched.

Execution ran three Steps in parallel across disjoint files, with every vault
write serialised to the coordinator, because concurrent plan-file mutation is a
known corruption path. Each executor committed path-restricted and verified its
own inventory. No cross-session clobber occurred, and one executor correctly
refused to edit an untracked file outside its scope when findings were
misattributed to it.
