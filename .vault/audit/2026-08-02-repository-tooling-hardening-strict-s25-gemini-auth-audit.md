---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:29bc2a7c6353460682593fdcc00f9fc5efceff16c93e9a0256d290a45feda031'
related: []
---
# `repository-tooling-hardening` audit: `Gemini credential boundary review`

## Scope

Independent read-only review of the current `W06.P12.S25` `gemini_auth.py` change. Inspected the whole module, its ACP call site, the governed strict-type plan, the existing direct-import credential tests, and the prior implementation. Checked untrusted JSON ingress, expiry boundaries, response validation before credential mutation, refresh serialization, reread and publication behavior, cleanup, errors and logging, and the absence of `Any`, `cast`, or suppression directives. Focused `basedpyright` and `ty` passed with zero diagnostics; the direct-import offline suite passed 22 tests. A credentialed live OAuth refresh was not run because no authorized Gemini OAuth credential is available in this environment.

## Findings

### refresh-expiry-window | medium | A nominally successful refresh can publish credentials that are still expired

`_required_token_number` accepts zero, negative, and positive lifetimes shorter than the configured proactive expiry buffer. `refresh_gemini_token` then writes the resulting credential record and returns success without reapplying `_is_expired`. With the current 120-second buffer, a response such as `{"access_token":"x","expires_in":0}` or `1` passes all response validation yet publishes a token that the module itself immediately considers expired. The next Gemini ACP launch reaches the headless-login path this function is intended to prevent. The response lifetime must be finite and leave the computed expiry safely beyond the configured buffer before any credential mutation or publication; focused direct-import regression coverage must exercise zero, negative, and sub-buffer lifetimes.

### stored-refresh-token-ingress | medium | The credential-file refresh token is not validated as a non-blank string before egress

Recursive JSON shape validation leaves each credential value as `JsonValue`, but the stored `refresh_token` guard only checks truthiness. Truthy arrays, objects, integers, and whitespace-only strings therefore reach the OAuth request data rather than producing the controlled re-authentication error used for a missing token. Validate the existing credential record's required refresh token with the same non-blank string boundary used for refreshed response fields before making a network request, and add direct local-file regressions for non-string and whitespace-only values.

### cross-process-refresh-serialization | medium | Concurrent processes can independently refresh and overwrite a rotated credential

`_refresh_lock` serializes coroutines only within one Python process. Separate VaultSpec processes using the same Gemini CLI home can both read an expired record, make refresh requests with the old refresh token, and each atomically publish a result. Per-process temporary names avoid partial bytes but do not serialize the read-refresh-publish transaction or reread after another process publishes a rotated `refresh_token`. Add an OS-level advisory lock around the transaction, then reread and re-evaluate expiry after acquiring it; preserve the current temporary cleanup and bounded Windows replacement retry. Prove this with real child processes and a controlled local protocol endpoint, not a mocked file or lock.

### prior-medium-findings-resolved | low | Response, stored-token, and process-serialization defects are repaired

The repaired `gemini_auth.py` rejects boolean, non-finite, non-positive, and buffer-or-shorter `expires_in` values before mutation; normalizes non-blank stored and response token strings before their respective egress or publication boundaries; and holds a persistent `msvcrt`/`fcntl` advisory lock from the post-acquisition reread through HTTP, durable temporary-file write, and atomic replacement. Its `finally` path offloads descriptor release, retains the lock file instead of unlinking it, and the direct process tests prove a waiting process rereads a peer publication without an HTTP request and that a crashed holder releases its descriptor lock. The focused offline suite passed 54 tests. No credentialed Google OAuth refresh was run.

### strict-test-private-helper-boundary | medium | The direct-import Gemini auth test does not pass the configured strict type checker

`test_gemini_auth.py` directly imports `_default_creds_path`, `_is_expired`, `_publish_credentials`, `_stored_refresh_token`, and `_validated_refresh_token` from `gemini_auth.py`. The current repository strict profile makes `reportPrivateUsage` an error, and focused Basedpyright on that test reports all five imports as errors. The production module itself has zero Basedpyright diagnostics, `ty`, Ruff check, Ruff format, and the whitespace check pass, and the 54 real-behavior tests pass; nevertheless the test file cannot be presented as a clean strict-type gate. The test must either prove behavior through an intentionally public, typed testing boundary accepted by architecture or be excluded through an explicitly governed test execution environment. Do not suppress the errors or make the production helpers public merely to satisfy the test.

## Recommendations

The first three medium findings are resolved by the post-review repair recorded above. Resolve `strict-test-private-helper-boundary` under the S25/S26 test-contract decision before claiming the Gemini test partition is strict-clean. Retain the explicit no-credential live-OAuth verification boundary.
