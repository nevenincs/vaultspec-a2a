---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cd71e003d2c06018656aa7d265abcfef055a9b0501be010426a9088fa013b750'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `OpenAI catalog P01.S05 review`

## Scope

Review P01.S05's generic prompt-free OpenAI-compatible `GET /models` discovery over a caller-bound API lane: endpoint and credential validation, authentication evidence, exact complete-list semantics, response bounds and cleanup, secret-safe failures, unsupported metadata, real-HTTP proof, and contract drift encountered during implementation.

## Findings

### sdk-only-collision | high | A concurrent variant hard-coded one provider and omitted transport bounds

Resolved during implementation. A concurrent SDK-only replacement restricted discovery to `api.openai.com`, branched on the OpenAI lane identity, and delegated response handling without the required one-MiB boundary. The accepted implementation restores a caller-bound base URL, derives only its same-origin `/models` endpoint, performs no provider-name branching, and enforces transport and model bounds. The collision changed no unrelated path.

### partial-content-catalog | high | HTTP 206 could publish a partial selectable model list

Resolved after reference audit. The transport now accepts exactly HTTP 200 after classifying 401 and 403 authentication evidence; every other status fails with a static error. A real local HTTP 206 response with `Content-Range` is refused and no partial model identifier enters a catalog or diagnostic.

### pagination-and-discriminator-gaps | medium | Some incomplete pages and malformed list shapes could be accepted

Resolved after reference audit. JSON `has_more`, `next`, `next_page`, and `next_cursor` signals and RFC Link relation lists containing the exact `next` token fail closed after one request. The documented top-level `object: list` and item `object: model` discriminators are required. Direct and real-HTTP tests cover cursor metadata, missing discriminators, and multi-token `prev next` and `next prev` relations.

### non-finite-timeout | medium | Infinity could disable the catalog refresh deadline

Resolved after reference re-review. Timeout validation now requires a finite positive non-boolean value before opening a connection. Direct async coverage refuses NaN, positive infinity, and negative infinity.

### openai-schema-wording | low | The reference misstated documented model-list metadata

Resolved through the Vault documentation workflow. The reference now records `object: list` and model `id`, `created`, `object: model`, and `owned_by`, and states that S05 deliberately projects only `id`. `created` and `owned_by` are not repurposed as descriptions, capabilities, or controls.

### non-ascii-bearer-leak | high | Header encoding could expose a credential in an uncaught exception

Resolved after independent review. A non-ASCII API key previously reached HTTP header construction, where an uncaught encoding exception retained the complete bearer value in its arguments. Present credentials must now be bounded visible ASCII before client construction, and HTTP or Unicode construction failures cross only a static error boundary. Direct coverage proves a non-ASCII secret is absent from exception text, representation, and notes storage.

### discarded-schema-fields-unvalidated | medium | Missing or malformed documented metadata could authenticate an incompatible shape

Resolved after independent review. Every model object must now carry `object: model`, a non-boolean non-negative integer `created`, a normalized bounded `owned_by`, and a normalized bounded `id`. `created` and `owned_by` are validated as authenticated endpoint evidence and then deliberately discarded; ten malformed metadata cases prove they cannot enter an available catalog.
Independent closure re-review returned PASS after the credential and schema remediations. No critical, high, medium, or low S05 finding remains open.
## Recommendations

- Register only provider-and-execution-mode lanes whose configured model-list endpoint is independently verified in P01.S06; leave unsupported enumeration unavailable.
- Retain exact-200, partial-content, pagination, body/model/key/identifier, finite-timeout, redirect, redaction, timeout, and cancellation proofs.
- Keep completed-turn admission separate; prompt-free catalog authentication does not prove that any selected model can complete a turn.
