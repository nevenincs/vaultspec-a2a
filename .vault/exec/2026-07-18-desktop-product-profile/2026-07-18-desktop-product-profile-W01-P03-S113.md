---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S113'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S113 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The heading and Scope placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Extract the pure closure selection core from the lock reconciliation authority so marker evaluation extras propagation graph resolution and platform filtering have one definition and re-express both reconciliation entry points as comparisons against it

## Scope

- `src/vaultspec_a2a/desktop/lock_reconciliation.py`
- `src/vaultspec_a2a/desktop/tests/test_lock_reconciliation.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add five frozen selection value types to `lock_reconciliation.py` - `LockedWheel`,
  `PythonPackageSelection`, `PythonClosureSelection`, `AcpNodeSelection`, and
  `AcpClosureSelection` - so a resolved closure is a first-class returnable value rather
  than a shape that only ever existed inside a comparison loop.
- Extract `resolve_python_closure_selection`, carrying the uv lock version and
  requires-python gate, marker evaluation, extras propagation, the excluded-capability
  guard, and the breadth-first graph closure. It returns packages sorted by canonical
  name with the approved root removed, each bearing its dependency tuple and its
  lock-pinned wheel candidates.
- Extract `resolve_acp_closure_selection`, carrying the Node runtime gate, lockfile-v3
  shape checks, the ACP-only project-root check, nested node resolution, os/cpu/libc and
  engine filtering, and optional/peer dependency classification. It returns nodes sorted
  by install path.
- Add `_locked_wheels`, which reads each lock record's wheel artifacts into exact
  pinned values and fails closed on any wheel entry lacking a URL, a `sha256:` hash, or
  an integer size.
- Add `compatible_wheels` beside `wheels` on the Python package selection, narrowed by
  the existing target-compatibility predicate. Choosing among several compatible
  candidates is deliberately left undecided here.
- Re-express `reconcile_python_closure_lock_bytes` and
  `reconcile_acp_closure_lock_bytes` as comparisons: each verifies the lock digest
  against its inventory, resolves the selection, then compares package sets, roots,
  dependency graphs, and artifact identities. Every existing rejection message and the
  target-SDK uniqueness check are preserved verbatim.
- Reduce `_verify_python_artifact_fields` to a comparison against a resolved package,
  matching the inventory's URL, digest, and size against the pinned candidates and then
  its filename against the matched candidate.
- Add eleven real-lock test cases driving the new resolvers against the committed
  `uv.lock` and `package-lock.json` across all five targets, plus one negative case
  executing the new unpinned-wheel raise.

## Outcome

The resolution walk now has one definition. Both reconciliation entry points remain
validation authorities and keep their public signatures, so `artifacts.py` is untouched;
they simply no longer own a private reading of the locks. The input-preparation
authority can now consume the same selection to build inventories, which makes a
declared closure and a resolved closure the same computation by construction rather than
two implementations that have to be kept in agreement.

Resolution was run against the real committed locks for the first time, and the two
numbers the follow-on Step depends on are now measured rather than estimated. The Python
closure is 82 packages on both macOS targets and both Linux targets and 84 on Windows -
the two extra being the `sys_platform == 'win32'` marked packages - resolved from 183
lock records with zero sdist-only packages and roots exactly equal to the project's 22
declared runtime requirements. The ACP closure is 104 packages per target, each with an
HTTPS tarball URL and a SHA-512 SRI, and exactly one native SDK per target.

One package has no target-compatible wheel: `cryptography` at the locked version
publishes macOS wheels for arm64 only, so the Intel-macOS target resolves a package it
cannot acquire. It is not reachable through an optional edge - the MCP dependency
requires the JWT library's crypto extra - so preparation for that one target fails
closed until the lock, the target matrix, or that edge changes. This is an owner-level
product decision about the shipped target matrix and is deliberately not resolved here.

The separate license sweep across the same closure, run to size the follow-on Step,
found 34 of 84 packages carrying no metadata license expression and therefore needing a
curated override, and four packages shipping no license bytes at all and therefore
needing committed external license artifacts.

Gates: `ruff format` on both touched files, `ruff check` clean across the desktop
package and the scripts tree, `ty check` clean on both files under the host platform and
under `--python-platform linux`, and the full desktop suite at 485 passed with 3
deselected - the 442-test baseline plus the 43 parametrized cases added here, with every
pre-existing test passing unmodified.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

- Behavior preservation was proven by leaving every pre-existing test in the
  reconciliation and artifact suites byte-unchanged. Two intentional nuances remain. Lock
  shape is now validated during resolution rather than during comparison, so when a
  malformed lock and a mismatched inventory are present together the lock error is
  raised first; both are the same error type from the same entry point. And a wheel entry
  that is not exactly pinned now fails closed during resolution, where it was previously
  merely unmatchable during comparison. The only records in the committed lock with
  unpinned wheel entries belong to an excluded capability that never enters the closure.
- The committed closure sizes are pinned as constants in the tests. A lock update will
  legitimately move them; the pin exists so that such a move is a reviewed change rather
  than a silent one, and the constants carry that note.
- The known Intel-macOS wheel gap is expressed as test data rather than tolerated
  silently, so when the pin, the matrix, or the dependency edge changes, the assertion
  reports it instead of quietly passing.
- Wheel selection ordering is out of scope here by instruction. Where several compatible
  candidates exist - measured at five to six packages per target, including a compiled
  wheel beside a pure-Python one for the SQL toolkit and two ABI floors for the crypto
  library - the selection returns all of them and leaves the choice to the consumer once
  that ordering is decided.
- No network access is performed by the resolvers or by any test added here; the
  real-lock cases read committed files only and run in well under a second each.
