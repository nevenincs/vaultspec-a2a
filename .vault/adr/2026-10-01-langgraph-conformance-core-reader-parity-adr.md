---
tags:
  - "#adr"
  - "#langgraph-conformance"
date: '2026-10-01'
related:
  - "[[2026-09-30-langgraph-conformance-audit]]"
  - "[[2026-07-16-authoring-contract-adr]]"
superseded_by: '2026-10-01-langgraph-conformance-core-runtime-dependency-adr'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:7fc69b116a959ce81e066ef901661da41c0d723685994b4d603480aa4504815e'
---
# `langgraph-conformance` adr: `core reader parity` | (**status:** `superseded`)

## Problem Statement

The authoring submitter refuses a document before it is written for the same body-link violations vaultspec-core refuses after it lands. The two enforcement points must agree on what is prose. The submitter strips code with regexes that read only single-backtick code spans, while vaultspec-core 0.3.2 reads code spans by backtick run length, so a wiki-link quoted inside a double-backtick span is refused by the submitter and accepted by core (`2026-09-30-langgraph-conformance-audit`, `submitter-link-stripping-drift`). How the submitter stays with core's reader is a dependency-strategy decision.

## Considerations

- vaultspec-core is a development and frozen-binary dependency of this repository, never a runtime one of the wheel (`pyproject.toml`, the `freeze` group and the deptry `DEP004` list).
- Tests may already import vaultspec-core, and one parity test already holds a submitter vocabulary to core's (`src/vaultspec_a2a/authoring/tests/test_core_grounding_parity.py`).
- Core's reader is one pure module of a few hundred lines with no I/O (`vaultspec_core/vaultcore/markdown.py`, `non_prose_spans`).
- The submitter runs inside a served graph turn; a subprocess or a heavy import per submit is paid on that path.

## Considered options

- Port core's prose reader into this package and hold it to core with a parity test that drives the real installed core. Kept: no runtime dependency, and drift fails CI on the core bump that introduces it.
- Make vaultspec-core a runtime dependency and import its reader. Rejected: it widens the shipped dependency closure to the whole framework package for one pure function, and couples the service's release to core's.
- Shell out to `vaultspec-core vault set-body --check` from the submitter. Rejected: a process per submit on the turn path, and a runtime requirement that core be on the service PATH.
- Keep the mirrored regexes. Rejected: they are the drift.

## Constraints

- The submitter's prose reader is a port of core's: the same fence, list-margin, HTML-comment and run-length code-span rules, producing the same non-prose spans for the same text.
- A test imports the installed vaultspec-core and asserts the port strips exactly what core strips, over constructed edge cases and over every record in this repository's own vault. The test has no skip path; a core layout change that breaks the import fails it.
- The port names no vault record and carries no claim beyond the rules it implements; its module docstring states that core's reader is the reference.

## Implementation

We will port `non_prose_spans` and its fence tracker from vaultspec-core into `src/vaultspec_a2a/authoring/` and strip body prose with it in the submitter, replacing the fence, comment and inline-code regexes. The wiki-link and markdown-link patterns stay as they are, matching core's. A parity test in `src/vaultspec_a2a/authoring/tests/` compares the port's stripped prose with core's `strip_non_prose` output.

## Rationale

The port keeps the runtime closure unchanged and costs nothing per submit, and the parity test turns silent drift into a failing check at the moment a core upgrade lands, which is when the lock is bumped and CI runs. That is the same coupling the grounding vocabulary already uses, made stronger by comparing behaviour instead of source text.

## Consequences

- A core upgrade that changes the reader fails the parity test until the port follows, so the port is maintained on core's schedule.
- The submitter now agrees with core on double-backtick spans, fences nested in list items, unclosed fences and comments that contain backticks.
- If core ever publishes the reader as a small standalone package, importing it replaces the port and this record is revisited.

Authorization: the user chose this option on 2026-10-01 and granted blanket approval in the same session.
