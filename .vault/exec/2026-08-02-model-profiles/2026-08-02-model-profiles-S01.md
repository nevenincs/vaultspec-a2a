---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:1a9d867233eb85d8b721ed30378b3f63e23cc4f626024118cf7945b9d808e4fb'
step_id: 'S01'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace model-profiles with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S01 and 2026-08-02-model-profiles-plan placeholders are machine-filled by
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
     The Add regression coverage for desired ACP model propagation and exact configuration RPC and ## Scope

- `src/vaultspec_a2a/providers/tests/test_factory.py and ACP protocol tests` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add regression coverage for desired ACP model propagation and exact configuration RPC

## Scope

- `src/vaultspec_a2a/providers/tests/test_factory.py and ACP protocol tests`

## Description

- Confirm the desired-model propagation half already lands in `test_factory.py`:
  Claude and Z.ai construction each assert the profile-resolved concrete name
  reaches both the chat model field and its frozen config snapshot.
- Confirm the live adapter exchange half already lands in the migration-surface
  test, which drives a real agent through initialize, session, and the
  configuration selection before reaping the subprocess.
- Add the missing deterministic layer as a new provider test module covering
  `_select_desired_model`, the production selection seam.
- Drive that seam over a real child process's stream pair, so the asserted
  request frame is the frame that actually left the process.
- Pin the request shape: the reserved request id, the method name, and params
  carrying `sessionId`, the `configId` read from the session's own advertised
  options, and the resolved value.
- Cover the four refusal paths: no model option advertised, the call rejected
  with a protocol error, the call accepted while confirming a different model,
  and a malformed confirmation.
- Cover the no-op path: absent a resolved model, no request is registered and
  the advertised options pass through untouched.

## Outcome

Regression coverage for both halves of the Step now exists, with the new module
supplying the cost-free floor beneath the live proof.

The load-bearing case is the accepted-but-unconfirmed selection. An adapter that
answers success while quietly keeping its own default would satisfy a
naive assertion, and would bill a run at the default tier while disclosure
showed the frozen low tier. Verifying the reported current value against the
requested one is what makes the profile claim a runtime fact rather than a
request.

Verification: the new module plus the team and model-profile suites run green at
153 passed. Lint and format pass on the added module. Whole-tree type checking
reports two diagnostics, both in the compiler test module and both caused by the
in-flight arity change to the worker preference resolver; the added module
contributes none.

The seam is proven wired rather than assumed: the selector is called from
session setup before any prompt is dispatched, not merely defined.

## Notes

Discovery found the propagation assertions and the live exchange already
present, so this Step reduced to the one genuinely absent layer rather than a
third copy of coverage that existed twice. Writing the obvious new tests without
that sweep would have duplicated both.

The live exchange lives in a module owned by a concurrent worker this session,
so it was read for coverage confirmation and deliberately left untouched; the
new deterministic coverage was placed in its own module to avoid contending for
that file.

The two type diagnostics are left standing rather than patched here. They belong
to the Step that proves compiler and factory resolution, and fixing another
Step's test arity from inside this one would blur the boundary.
