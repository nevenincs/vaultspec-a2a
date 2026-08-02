---
tags:
  - '#research'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:a0054b983244300e27d117861e50dc5dd0bf6c30a6d479defcd1e1ff31eaf922'
related:
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference]]"
---
# `llm-context-provider-abstraction` research: `ACP v1 client wire`

ACP v1 client requests from an agent currently reach a hand-written response layer whose observed filesystem and terminal shapes diverge from the installed `@agentclientprotocol/sdk@1.2.1` contract. The evidence favors a focused replacement with the schemaâ€™s v1 forms and protocol-meaningful real-stdio regression probes; whether to retain legacy shapes during that replacement is the narrow decision for the ADR. The existing provider-harness decision remains the parent boundary and is not reconsidered here.

## Findings

### The wire mismatch is limited but protocol-visible

The implementation uses byte-offset filesystem reads, scalar terminal output status, a numeric signal, and terminal-map removal on kill. The SDK schema instead specifies a line-based read request, exit-status objects, a string signal, and terminal lifetime surviving kill. The concrete map is recorded in `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference`; authoritative local source is `@agentclientprotocol/sdk@1.2.1` at `node_modules/@agentclientprotocol/sdk/schema/schema.json:328-367`, `:1178-1233`, `:1256-1378`, and `:8050-8145`.

### Session scoping and output retention must move together with the shape correction

The schema requires `sessionId` on each relevant request and defines `outputByteLimit` as an output-retention bound. Validating session identity and owning the bounded output lifecycle prevents a conforming shape from becoming a cross-session capability leak or an unbounded capture path. The runtime already retains the session identity after setup, while the current terminal map has no retention model. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference`; `src/vaultspec_a2a/providers/_acp_types.py:117-122`.

### Direct cutover and compatibility shims are distinct policy options

A direct cutover deletes the unstandardized request and response semantics, keeps one contract, and permits tests to validate exact v1 payloads. A temporary dual parser could tolerate unverified older agent behaviour, but it expands the public surface, creates ambiguity for byte versus line pagination, and requires an expiry/removal mechanism. A protocol-version split is not supported by evidence: this runtime explicitly initializes protocol version 1 and the real migration test proves only session setup, not legacy filesystem or terminal requests. `src/vaultspec_a2a/providers/_acp_session.py:58-86`; `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py:70-124`.

### The supported-client impact is bounded and must be proved at the wire

The real Claude ACP adapter integration covers initialize and `session/new`, but no current test establishes reliance on the divergent methods. A focused subprocess probe against the registered adapter can validate request framing and lifecycle without mocks, fakes, or a claimed compatibility story. The reference does not establish other client support; that is intentionally uninvestigated. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference`.

## Sources

- `2026-02-25-llm-context-provider-abstraction-adr`
- `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference`
- `node_modules/@agentclientprotocol/sdk/package.json`
- `node_modules/@agentclientprotocol/sdk/schema/schema.json:328-367`
- `node_modules/@agentclientprotocol/sdk/schema/schema.json:1178-1233`
- `node_modules/@agentclientprotocol/sdk/schema/schema.json:1256-1378`
- `node_modules/@agentclientprotocol/sdk/schema/schema.json:8050-8145`
- `src/vaultspec_a2a/providers/_acp_session.py:58-86`
- `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py:70-124`
