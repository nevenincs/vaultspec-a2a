---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S110'
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
     The S110 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Add the wheel selection authority deriving a deterministic per-target ordered supported-tag list from the pinned packaging dependency and ranking every admitted lock wheel by best tag index with a fixed vector guarding the derivation and ## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_input_authoring.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the wheel selection authority deriving a deterministic per-target ordered supported-tag list from the pinned packaging dependency and ranking every admitted lock wheel by best tag index with a fixed vector guarding the derivation

## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_input_authoring.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add the input-authoring module with the wheel selection authority as its first
  landed capability. The module docstring states its full eventual role - resolve,
  acquire, derive, emit - while this Step delivers only selection.
- Add `target_platform_tags`, deriving one target's ordered platform-tag sequence from
  the triple string and the fixed compatibility baselines rather than from a per-target
  table: Windows is the single `win_amd64`, Linux mirrors the standard manylinux descent
  from the glibc baseline, macOS delegates to the packaging primitive.
- Add `target_supported_tags`, composing the packaging `cpython_tags` and
  `compatible_tags` generators with an explicit `(3, 13)` version, the `cp313` ABI, and
  the derived platform sequence, so the order is the reference installer's: compiled
  version-specific wheels first, descending stable-ABI floors next, pure-Python last.
- Add `select_target_wheel`, ranking the admitted wheels by best supported-tag index and
  breaking ties by build tag descending then filename ascending, a total order over the
  lock. An empty admitted set raises fail-closed.
- Mirror packaging's manylinux descent faithfully: the fixed glibc baseline, the legacy
  alias interleaved immediately after the `_x_y` form it aliases, and the per-architecture
  floors that match packaging's own oldest-supported rule.
- Reuse the compatibility authority's baseline constants directly rather than restating
  them, so one baseline governs both the compatibility predicate and the selection order.
- Add the required fixed-vector tests over the derived tag lists, the real-lock selection
  tests asserting the exact chosen wheel per package, a determinism test, the fail-closed
  empty-admitted-set test, and the build-tag tie-break test.

## Outcome

Wheel selection is now a single authority answering which admitted wheel a target ships,
beside the compatibility predicate that answers whether a wheel can run at all. It adopts
the reference installer's tag-priority model wholesale rather than encoding a bespoke
ordering, so the selection reproduces host-independently the choice a baseline target
machine's installer would make. On the real committed lock this resolves every
previously untied package to its compiled variant: the SQL toolkit to its cp313 platform
wheels over the pure-Python fallback, the crypto library to cp311-abi3 on the higher
glibc floor over the lower, and the character, websocket, wrapper and regex packages to
architecture-specific wheels over `universal2` - removing both the pure-Python
performance regression and the `universal2` size doubling.

The derivation is pinned by fixed vectors so a packaging upgrade that reorders or renames
tags fails visibly rather than silently changing which wheel each capsule carries. The
per-target supported-tag counts are 567 for macOS-arm64, 393 for Linux-arm64, 799 for
Linux-x86_64, and 45 for Windows; the underlying platform-tag counts are 19, 13, 27, and
1. Selection chooses only among wheels the compatibility predicate already admits, and a
package whose admitted set is empty still fails preparation closed.

Gates on the settled four-target base: `ruff format` and `ruff check` clean across the
desktop package and the scripts tree, `ty check` clean on both touched files under the
host platform and `--python-platform linux`, and the full desktop suite at 502 passed
with 3 deselected - the four-target baseline plus the 28 selection cases added here.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

- Design decision worth preserving: the platform sequence is parsed from the target
  triple, so the module holds no target enumeration. There is no per-target table to keep
  in step with the shipped matrix, and the same code runs unchanged whether the matrix
  holds four targets or five. The fixed-vector test still enumerates the shipped targets -
  that enumeration is the intentional review gate, and covering exactly the shipped
  targets is correct.
- Two implementation facts behind the platform-tag derivation, recorded so a future
  reader does not read the asymmetry as arbitrary. The macOS order comes straight from
  packaging: its platform primitive is callable host-independently when both the version
  and architecture arguments are passed, so no reimplementation is needed. Linux must be
  mirrored instead, because packaging's manylinux tag generator is both private and
  host-gated - it returns nothing off a Linux host and reads the running host's glibc -
  so it cannot be called from a Windows authoring host or for a cross-target build. The
  mirror reproduces its descent exactly against the fixed baseline: the legacy-alias
  interleave position and the per-architecture floors are part of the ordering, not
  decoration.
- Scope discipline: this Step is selection only. Acquisition into the content-addressed
  cache is the next Step, and license derivation with the curated overrides input and
  inventory emission is the Step after. The module docstring names the full arc so the
  partial delivery is not mistaken for the finished authority; no acquisition, derivation,
  or emission code is present yet.
- The one deliberate type-checker suppression is a `ty: ignore[invalid-argument-type]` on
  the fail-closed negative test that passes a non-target to prove the runtime guard
  raises - the type system cannot express an invalid argument the guard exists to catch.
  It matches the established convention in the neighbouring archive tests.
