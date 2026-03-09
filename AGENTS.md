# Repository Instructions

## Audit Workflow Mandate

This repository follows a rolling audit/research/implementation cycle.
Implementation does not close the cycle; each implementation pass is expected
to surface additional issues, follow-up work, and contract drift.

Required workflow for every implementation pass:

1. Implement the targeted change set.
2. Run a code review pass against the actual implementation.
3. Classify every surfaced issue by severity and type.
4. Add every review finding to the audit task queue or audit documents.
5. Treat a pass as complete only when implementation, review, and queue
   updates are all done.

Additional rules:

- Do not treat "code written" as equivalent to "issue closed".
- When a conclusion from implementation changes the understanding of the
  system, update the relevant audit/research trail.
- New issues introduced or discovered during implementation must be captured,
  even when they are not fixed in the same pass.
