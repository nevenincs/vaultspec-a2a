---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:b7c9eebd5e161cf3239f24536454aabf7ce62509f045f3fd67777bedc55b5547'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-implementation-review-audit]]"
---

# `embedded-runtime-remediation` audit: `W04.P10.S47 cooperative server owner formal review`

## Scope

Formal review of prerequisite commit `24dab547465e2bb846dfba0f8b9d87e95c41b7e8` for `W04.P10.S47`. The review inspected all six committed paths against the approved plan, the remediation research and rolling audit, the no-legacy contract, and the concurrent unstaged `W04.P10.S49` work. It independently ran the claimed two test modules from an archived copy of the exact commit so the S49 working-tree changes could not affect the result.

The commit correctly removes the process-directed Windows `SIGINT` path, constructs the current Uvicorn `Server` in process, injects a callback that sets `should_exit`, requires attach authentication and lifecycle-receipt ownership, refuses a missing owner before closing admission, closes admission before scheduling shutdown, and delays the callback until after the handler has returned its 202 body. The exact archived test run passed 12 tests in 19.43 seconds. A separate exact-commit probe confirmed a correctly authenticated request without `request_server_shutdown` returns typed 503 while the admission gate remains open. The commit does not change discovery, so S48 retains discovery ownership. No compatibility route, deprecated API, provider fallback, or retired state support was added.

Disposition: **FAIL**. The cooperative direction is correct, but the lifecycle owner boundary is not closed under malformed in-process state and the test evidence does not exercise the production Uvicorn callback. The source and Step Record also retain obsolete signal wording and leave the shared `app.py` ownership implicit. S47 remains open.

## Findings

### lifecycle-owner-shape | medium | A malformed owner closes admission and returns 202 without initiating shutdown

Type: lifecycle correctness and fail-closed validation. Status: open; review-blocking for `W04.P10.S47`. `shutdown_endpoint` treats every non-`None` `request_server_shutdown` value as a valid owner. An exact-commit probe seated an ordinary object at that state key: the endpoint returned 202, permanently closed admission, and the deferred timer later raised `TypeError` instead of requesting shutdown. The route must establish a callable current lifecycle owner before changing admission, then prove both absent and malformed owners return 503 with admission still open.

### cooperative-owner-production-proof | medium | The changed test replaces rather than exercises the Uvicorn owner

Type: test integrity and portability evidence. Status: open; review-blocking for `W04.P10.S47`. The 12-test run is real and useful for authentication and drain-gate behavior, but only one test observes the new callback and it injects a list-appending lambda into application state. No test invokes the production `main` ownership seam or an actual Uvicorn `Server.should_exit` transition over HTTP. Therefore the suite cannot distinguish the committed production wiring from a broken or absent assignment at `app.py` lines 675-676. Add a bounded production-owner test that observes the actual in-process server transition and response-before-shutdown ordering without a process signal.

### retired-signal-wording | low | Current source still describes the removed SIGINT path

Type: source documentation accuracy and no-legacy hygiene. Status: open; review-blocking for `W04.P10.S47`. The module comment at `admin.py` line 14 still says the delay precedes a `SIGINT`-driven shutdown, and the changed test docstring at `test_gateway_drain.py` lines 124-125 says a self-SIGINT is discarded. The implementation removed that mechanism and the test now explicitly waits for the callback. Replace both statements with the current cooperative server-owner behavior; do not preserve the retired signal path as current guidance.

### shared-app-owner-traceability | low | The Step Record does not name the callback lines as S47's shared prerequisite

Type: lifecycle traceability. Status: open; review-blocking for `W04.P10.S47`. The plan names `admin.py` as S47's canonical path and `app.py` as S49's. This prerequisite necessarily changes `app.py` lines 663-677, with lines 675-676 constructing and injecting the cooperative owner. The Step Record lists `app.py` under Changes but its Scope still names only `admin.py`; the research describes the prerequisite without declaring the shared-line boundary. Correct the record to state that S47 owns the current Uvicorn owner construction/injection and S49 owns the total deadline, stream drain, and escalation evolution around that seam. This preserves S48's separate discovery ownership.

### feature-index-validation | low | The implementation commit leaves its feature index stale

Type: Vault lifecycle validation. Status: open; review-blocking for `W04.P10.S47`. An exact-commit Core check completes every substantive validation but reports that the remediation feature index has 17 links for 18 documents because the new S47 execution record is absent. The Step Record records Ruff, Ty and tests but no Core result. Rebuild the feature index through Vaultspec Core and retain the clean validation result with the corrected S47 evidence. The live shared worktree also contains an uncommitted S49 execution record, so the correction must coordinate with that owner rather than absorbing its unfinished document accidentally.

## Recommendations

- Validate the lifecycle owner as callable before closing admission, and add absent plus malformed-owner assertions that retain open admission.
- Drive the production owner seam with a bounded real-server test proving an authenticated receipt-bound POST receives 202 before cooperative `should_exit` takes effect.
- Remove the two stale SIGINT descriptions.
- Amend the S47 Step Record and research trail with the exact shared `app.py` ownership boundary while leaving S49 and S48 ownership intact.
- Rebuild the remediation feature index through Core after coordinating the concurrent S49 record, then record the clean feature check.
