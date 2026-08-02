---
tags:
  - '#exec'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:68089dcdab4eea262077214d671af48e6fd7266513a15ef5a3cc6fdb4ea21f4a'
step_id: 'S03'
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
     The S03 and 2026-08-02-llm-context-provider-abstraction-plan placeholders are machine-filled by
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
     The Return ACP v1 exit-status objects and preserve killed terminal identity until explicit release. and ## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Return ACP v1 exit-status objects and preserve killed terminal identity until explicit release.

## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`

## Description

- Add a signal namer that resolves a signal number to the protocol's string form through the standard library enum, falling back to the bare digits where the running platform does not define that signal.
- Add a single exit-status builder returning the v1 status object, or nothing at all while the process is still running.
- Report a signal death as a null exit code beside the named signal, and a normal exit as the code beside a null signal.
- Return the status object from the terminal output handler in place of the bare return code.
- Return the status object's fields from the wait-for-exit handler in place of a top-level code and numeric signal.
- Stop the kill handler retiring the terminal id, leaving release as the only handler that ends addressability.
- Update the two containment assertions the shape and lifetime changes invalidate, so the tree stays green at this commit.

## Outcome

Terminal exit is now reported in one shape built in one place, and the kill and release verbs carry distinct meanings. The previous bare return code could not represent a signal death: on POSIX the value is negative, which the schema's unsigned exit code cannot hold, so a reader was told the process returned a code it never returned. Killing a terminal also used to retire its id in the same breath, which made the output the agent killed the command to inspect permanently unreachable; the id now survives kill and is removed only by release.

Modified files: the ACP RPC handler module, and the terminal containment test.

Real-behaviour verification drove genuine subprocesses, no doubles. The scoped test file passes at five of five. A direct probe against the production builder confirmed each branch on this host: a normal exit reports its code beside a null signal, a still-running process yields no status at all so the optional field is correctly omitted, and the enum resolves a defined signal to its name while an undefined number degrades to digits rather than raising.

Whole-tree type checking reports two diagnostics, both in a graph test owned by another concurrent lane and both present before this work; the handler module and its tests contribute none. Lint and format checks pass on both modified files.

## Notes

Three failures in the kimi conditioning test file are NOT from this work and were confirmed by evidence rather than assumption. All three raise from the session module demanding a configuration-options field on session setup. That requirement is absent from the committed tree and present three times in a concurrent lane's uncommitted session-module changes; this Step's diff never mentions that field and touches no session-setup path.

Two boundaries are recorded rather than papered over. First, the signal branch that matters most cannot be proven on this host: Windows has no signal death, so killing a process yields a positive return code and the negative-return-code path is unreachable here. It is reachable on POSIX and remains unproven until the suite runs there. Second, and for the same reason, the signal namer returns digits rather than a name for signals Windows does not define, so the string differs by platform for the same numeric signal. Both belong in the strict closure Step's finding classification.

The wait-for-exit handler still reads an undocumented timeout field from request parameters that the v1 schema does not define for that request. It is out of this Step's scope and was deliberately left unchanged rather than altered silently, but it is a live instance of the decision's prohibition on undocumented payload acceptance and is carried forward as a finding for the closure Step.

This Step was executed ahead of the two rows before it because both are blocked on files owned by a concurrent lane. Session-ownership validation needs the active session identifier, which the handlers cannot reach today, and output retention needs per-terminal state beyond the process handle; both additions land in the session context type, which currently carries another lane's uncommitted work and cannot be committed without sweeping it. This Step needed neither, so it was taken first while keeping the handler module serialized.
