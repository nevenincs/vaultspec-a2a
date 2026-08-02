---
tags:
  - '#exec'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c8a49b521ee82cfdc1922c56edfa46b90f5ff51830ec84818a3cf7f81702b3b9'
step_id: 'S04'
related:
  - "[[2026-08-02-llm-context-provider-abstraction-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace llm-context-provider-abstraction with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-08-02-llm-context-provider-abstraction-plan placeholders are machine-filled by
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
     The Replace obsolete terminal-containment expectations with exact ACP v1 response and lifetime assertions. and ## Scope

- `src/vaultspec_a2a/providers/tests/test_terminal_containment.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace obsolete terminal-containment expectations with exact ACP v1 response and lifetime assertions.

## Scope

- `src/vaultspec_a2a/providers/tests/test_terminal_containment.py`

## Description

- Replace the single-field probes on the terminal output and wait responses with whole-result comparisons.
- Add a proof that the exit status key is absent, not merely null, while the command is still running.
- Add a proof that a failing command reports its own non-zero code beside a null signal.
- Add a proof that a killed terminal still answers output, exit and a second kill, and that only release retires the id and restores the refusal path.
- Add a small helper that spawns a real allowlisted terminal child from a script body.

## Outcome

The terminal surface is now asserted as whole responses rather than field probes, so a renamed or additional key fails instead of passing unnoticed. The lifetime the earlier implementation could not express is covered end to end: kill stops the command while the id stays addressable, and release is the only verb that retires it.

Modified files: the terminal containment test.

Every test drives genuine subprocesses through the production handlers; there are no doubles, and nothing is skipped. The scoped file passes at eight of eight.

The assertions were confirmed load-bearing by mutation rather than assumed. Restoring the two behaviours the previous Step replaced - retiring the terminal id inside kill, and reporting the bare return code as the exit status - fails three of the eight tests. The production module was restored from version control immediately afterwards and confirmed clean.

The killed-command status asserts the schema's exclusivity - a null code beside a named signal, or a code beside a null signal, never both and never neither - instead of one host's answer. Windows has no signal death, so pinning this host's concrete result would have hardcoded a platform accident into a protocol assertion.

Lint and format pass on the file. Whole-tree type checking reports diagnostics only in a graph test and a service test owned by other concurrent lanes; this file and the handler module contribute none. The out-of-scope desktop process-tree test that also drives the kill handler was run and passes, confirming the lifetime change has no blast radius there.

## Notes

A real defect surfaced while writing the killed-terminal proof, and it is a finding rather than a test problem. The output handler drains the live pipe destructively and retains nothing, so output written before a kill is unrecoverable after it - the first draft of the test asserted the pre-kill marker came back after the kill and failed with an empty string. Retaining output under the requested byte cap is the separate retention row, so this test now reads the marker through the handler before the kill and the post-kill retrieval assertion is deliberately left for that row. Until it lands, an agent that kills a command to inspect what it printed still gets nothing back.

The destructive drain has a second consequence worth carrying to the closure Step: because each call consumes the pipe, two consecutive output requests return different content, and no single call is guaranteed to return everything produced. The pre-kill read in this test therefore accumulates across calls rather than trusting one.

This row was taken before the two remaining rows of the first Phase, both of which are blocked on a concurrent lane's uncommitted changes to the session context type. The plan anticipates this ordering, noting that this row proceeds independently once the terminal lifetime is defined.
