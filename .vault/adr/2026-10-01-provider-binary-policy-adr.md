---
tags:
  - '#adr'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:bbd0271f9d51eeba5d4ef7bf98b4f7783176913b0407cc6cd29d36414eabc86d'
related:
  - "[[2026-10-01-provider-binary-policy-research]]"
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]"
  - "[[2026-08-02-provider-capability-evidence-adr]]"
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-21-capsule-install-layout-adr]]"
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
---

# `provider-binary-policy` adr: `profile-scoped provider binary authority, proof-bound version ranges, and recorded runtime identity` | (**status:** `accepted`)

## Problem Statement

A served profile is admitted only after a real turn completed on its lane, but
nothing binds that admission to the binary that completed it, and no run records
which binary ran. On this host the lock-vendored Claude CLI is `2.1.207` and the
PATH one is `2.1.286`; under the desktop capsule, whose promise is an immutable
runtime, the Node runtime and the ACP adapter come from capsule assets while the
CLI that does the work still comes from PATH. Two further gaps ride the same
seam: the declared `CLAUDE_CODE_OAUTH_TOKEN` setting is read by no production
code while a test prerequisite counts it as a credential, and a provider session
is created per model call with an unreachable resume branch left in the code.
Each is cheap to fix in isolation and wrong to fix in isolation, because they all
answer one question: what runtime a served turn runs as, and what the service can
later prove about it. Grounding: `2026-10-01-provider-binary-policy-research`;
findings `claude-binary-split`, `capsule-claude-binary-still-overridden-by-path`,
`no-cli-version-identity`, `oauth-token-setting-unwired`, and
`per-call-provider-sessions` in `2026-09-24-architecture-review-audit`.

## Considerations

- The served-profile rule's unit of proof is a lane, and a lane's binary changes
  under the service without notice: the native installer auto-updates by design
  and moved 5 patch releases in the week between the audit and this record
  (research).
- Profile-scoped runtime authority already exists for Node and the adapter and is
  already classified as `runtime_authority` on every launch
  (`src/vaultspec_a2a/providers/_factory_commands.py:227-258,302-311`); the CLI is
  the one asset outside it (`src/vaultspec_a2a/providers/cli_resolution.py:111-131`).
- The capsule supply chain already builds its ACP closure from the committed
  `package-lock.json` and publishes a descriptor digest, so a vendored CLI adds a
  path, not a trust model (`2026-07-21-capsule-install-layout-adr`).
- Upstream supports exact pinning, update suppression, and a start-time version
  range from settings, and publishes a signed per-release checksum manifest
  (research).
- Injecting an OAuth token is not neutral: upstream precedence places it above the
  operator's `/login` credential, so injection changes the identity a turn runs as
  (research), which the no-credential clause of the 2026-08-02 amendment to
  `2026-07-15-agent-harness-provisioning-adr` exists to prevent.
- The checkpoint is already the only transcript, which is what makes recovery and
  forking provider-agnostic; a provider-native session would be a second source of
  truth that LangGraph's resume path cannot reconstruct
  (`per-call-provider-sessions`).

## Considered options

- **Host binary everywhere, as today.** Rejected: it serves an unrecorded, silently
  changing runtime, and it contradicts the desktop profile's immutability promise.
- **Lock-vendored binary everywhere.** Rejected as a blanket rule: it is correct for
  the capsule and for a container image, but on a developer host it diverges from
  the CLI the operator logs in and debugs with, and it freezes security fixes behind
  a lock bump on a lane that has no other update path.
- **Profile-scoped authority with one resolver and a recorded identity (chosen).**
  Capsule and container profiles run a pinned, service-owned binary; a checkout
  profile runs the service's installed CLI; every profile names an absolute path and
  records what it ran.
- **Pin lane proof to an exact binary version.** Rejected for host-PATH profiles: with
  multiple patch releases a week, every update would unserve the product; rejected
  only there, and kept exactly for pinned authorities.
- **Leave the proof unbound and warn.** Rejected: a warning is not an admission
  decision, and the served-profile rule requires enforcement where profiles are
  served.
- **Delete the OAuth token setting and require an ambient export.** Kept as the
  fallback if the exception below is declined: it is honest and preserves the
  no-credential contract, but it leaves a headless container lane with no supported
  credential path.
- **Resume provider-native sessions per thread.** Rejected now: a Claude transcript is
  same-machine, lives in the operator's config home under the operator's retention,
  and would disagree with the checkpoint after any recovery; upstream itself
  recommends carrying results as application state instead (research).

## Constraints

Binding:

- Exactly one resolver answers "which CLI will this child run", for the catalog
  probe and the served turn alike. No second answer may be introduced in a
  settings field, a launch spec, or a spawn-time lookup.
- A resolved launcher is an absolute path chosen from a trusted search path, never
  a bare name and never a path influenced by the agent's environment or working
  directory. This restates `launcher-path-hijack` and is unchanged by this record.
- When a desktop capsule root is armed, the Claude CLI is a capsule-owned asset.
  An absent capsule CLI is a fail-loud repair condition, never a PATH or vendored
  fallback, and an inherited `CLAUDE_CODE_EXECUTABLE` does not override it.
- A lane is served only while its resolved binary lies inside the version range its
  proof declares. Out of range is ineligibility with a typed reason at the
  eligibility service, not a log line.
- Every run records the runtime identity that produced it, durably, before any
  claim about that run's behaviour is made.
- No credential is injected into a provider child except under an explicitly
  declared channel. The default stays the operator's own resolution, and
  `ANTHROPIC_API_KEY` remains scrubbed unconditionally so flat-rate billing cannot
  silently become metered.
- A capability the production path cannot reach is not kept in the code.

Implementation hypotheses, revisable within the constraints: the exact ceiling
rule for host-PATH lanes, the storage shape of the identity record, and whether
a per-launch version probe stays memoized per process or is cached per path and
mtime.

## Implementation

We will make the provider launch identity profile-scoped, proof-bound, and
recorded; keep provider sessions per model call; and wire the OAuth token only
behind an explicitly declared headless channel. Scope is the Claude, Z.ai, and
Codex execution lanes and the desktop, Compose, and checkout profiles. The ACP
wire contract, the permission model, the durable event log, and the continuation
model are out of scope and keep their current owners.

**D1 Binary authority is the profile's, not the PATH's.**
`pin_claude_executable` resolves in this order and records which rung answered:
the capsule asset when `settings.capsule_assets_root` is armed, exclusively
and fail-loud; an explicit absolute `claude_cli_executable` setting only when
no capsule root is armed; a
`CLAUDE_CODE_EXECUTABLE` already present in the child environment; this service's
own PATH; and finally the lock-vendored binary resolved by this service rather
than by the adapter's internal fallback. The capsule path is a new
`capsule_claude_executable(root)` beside the existing Node and adapter path
authorities, pointing at the verbatim npm projection
`<root>/node_modules/@anthropic-ai/claude-agent-sdk-<platform>-<arch>[-musl]/claude[.exe]`
and selecting the libc variant by the same rule the adapter uses
(`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:161-196`);
capsule validation adds it as a third required asset
(`src/vaultspec_a2a/desktop/profile.py:313-335`). The Compose worker image
installs one exact CLI version and names it through the setting. The resolver
never returns `None` into a served launch: a run whose CLI cannot be resolved is
refused with a typed reason.

**D2 A lane proof carries the version range it covers.** `LaneProof`
(`src/vaultspec_a2a/providers/lane_admission.py:112-122`) gains `binary`,
`proved_version`, `floor`, and `ceiling_exclusive`. For the capsule, the pinned
setting, and the lock-vendored rungs the admitted range is exact equality with the
version the proof recorded. For the host-PATH rung the range is
`floor <= version < ceiling_exclusive` with the ceiling at the next MINOR, the
smallest range that neither unserves the product on a routine patch nor lets a
feature-level change ride an old proof. Admission probes the resolved binary's
version once per launch identity, memoized per process (0.22 s measured), and an
out-of-range result makes the lane ineligible with a typed blocker that
`provider-catalog` selection, provider construction, and child spawn all read. A proof moves only by rerunning its cited
live test against the new binary and recording that version by hand. CI pins
`npm install -g @openai/codex@<exact>` (`.github/workflows/test.yml:223`) and runs
`npm audit signatures`, and the pinned version is that lane's `proved_version`.

**D3 Every run records what it ran.** At the first successful `initialize` of a
lane in a run the worker captures provider, catalog key, runtime authority,
adapter name and version from `agentInfo`, adapter entry path, CLI absolute path,
CLI version, Node version for a node-entry launch, auth mode, and the
provider-native session id, and persists one row per run and lane. The existing
INFO line stays (`src/vaultspec_a2a/providers/acp_chat_model.py:416-439`). No
per-run binary digest: hashing the 259 MB binary measured 1.9 s, the lock and the
capsule descriptor already attest the pinned rungs, and for a host binary the
version and absolute path are what a run can honestly claim. Disclosing the
identity on the dashboard edge, for example inside
`FrozenTeamAssignmentSummary` (`src/vaultspec_a2a/api/schemas/gateway.py:261-286`),
is deliberately deferred: it is a cross-repository contract event under
`2026-07-14-a2a-edge-conformance-adr` R6 and is scheduled separately.

**D4 The OAuth token is wired as a declared channel, not as an ambient default.**
A new `claude_auth_channel` setting takes `subscription_login` (default) or
`oauth_token`. Under `oauth_token` the worker injects
`settings.claude_code_oauth_token` into the child as `CLAUDE_CODE_OAUTH_TOKEN`,
refuses the lane when the value is empty rather than running unauthenticated, and
records `auth_mode="oauth_token"` in the D3 row. Under the default the setting is
never read into a child, and an operator's own ambient export keeps passing
through the existing allowlist
(`src/vaultspec_a2a/workspace/environment.py:146-161`) as their own choice. Two
honesty defects close with it: the credential prerequisite
(`src/vaultspec_a2a/conftest.py:178`) must probe the production resolution rather
than the settings value, and `.env.example` must state that a `.env`-only token
authenticates nothing outside the declared channel.

**D5 Provider sessions stay per model call.** One spawn and one `session/new` per
Claude call, one ephemeral thread per Codex call; the LangGraph checkpoint remains
the only authoritative transcript. The unreachable `session/load` branch and the
`session_id` option are removed
(`src/vaultspec_a2a/providers/_acp_session.py:744-745`,
`src/vaultspec_a2a/providers/acp_chat_model.py:134-136`), because a capability no
production path can reach is a defect, not a feature. The provider-native session
id is recorded by D3 so an operator can still find the CLI's own transcript.

**Verification.** Each commitment is proven by a real-behaviour test: a capsule
tree whose CLI asset is absent refuses to arm, and one whose asset is present is
the path a served launch resolves even with a `claude` earlier on PATH and a
`CLAUDE_CODE_EXECUTABLE` set; a lane whose resolved binary reports a version
outside its proof range is ineligible in `provider-catalog` and refused at construction and child spawn, with
the in-range case served; a completed live turn writes an identity row carrying
the CLI version the same binary reports; under `subscription_login` the child
environment carries no token derived from settings, and under `oauth_token` with
an empty setting the lane refuses; and a grep-level test proves no production
caller sets a provider session id.

## Rationale

The knockout is that admission and identity are the same fact. The served-profile
rule admits a lane because a real turn completed on it, and the audit shows the
service cannot say which binary completed it, cannot keep serving the same one,
and under the capsule does not even run the one its own runtime promise names.
Profile-scoped authority fixes all three with the classification the launch path
already carries, so the change is a branch and a record rather than a new
subsystem. Binding the proof to a range rather than to a version is what keeps the
rule enforceable in practice on a CLI that ships several releases a week, and
pinning exactly where the service owns the bytes is free. The credential channel
is deliberately declared rather than inferred, because upstream precedence makes
an injected token outrank the operator's login: silent injection would change who
a turn runs as, which is exactly the surprise the no-credential clause was written
against, while a declared channel gives a headless container the only credential
path it has. Per-call sessions are kept because the alternative buys unmeasured
savings with a second transcript that is same-machine, operator-retained, and
unreconstructable after a checkpoint recovery. Grounding:
`2026-10-01-provider-binary-policy-research`.

## Consequences

- A served turn becomes explainable after the fact: the run says which adapter,
  which CLI version, and which authority produced it.
- Desktop gains the immutability it already claims, and a capsule that lost its CLI
  asset fails loudly at arm time instead of quietly borrowing the host's.
- Accepted cost: a pinned lane's security fixes arrive on a lock or image bump, so
  the bump cadence becomes an operational obligation rather than a background
  update; `npm audit signatures` and a scheduled bump are the mitigation.
- Accepted cost: a host-PATH lane can become ineligible after an upstream minor
  release until its proof is rerun. That is the intended behaviour of the
  served-profile rule and is visible as a typed reason, not a failure.
- Operators who relied on a `.env` token without an ambient export will see a
  refusal where they previously saw an unauthenticated child; this is a visible
  behaviour change and belongs in the release note.
- The identity record is internal until the edge contract event lands, so the
  dashboard cannot display runtime identity yet.
- Reconsider D5 when a measured cost or latency case exists for session reuse and
  an a2a-owned session store removes the same-machine and retention objections;
  reconsider D2's ceiling rule if upstream minor releases stop carrying behaviour
  changes that invalidate a turn proof.

## Proposed reconciliation of existing decisions

These edits are proposed, not applied. Each names the record, the clause, and the
replacement.

- `2026-07-15-agent-harness-provisioning-adr`, amendment of 2026-08-02, paragraph
  **Stack identity**. Its text fixes the stack as the project-pinned adapter
  "driving the operator's installed `claude` CLI `2.1.220` through
  `CLAUDE_CODE_EXECUTABLE`". Proposed replacement clause: "The adapter is
  project-pinned; the CLI it drives is profile-scoped and resolved by one service
  seam - a capsule asset under an armed desktop capsule, the image-pinned binary
  under Compose, the service's installed CLI in a checkout, and the lock-vendored
  binary as an explicit last resort. The version in force is recorded per run, not
  fixed by this record."
- Same record, same amendment, the no-auth clause "the provider layer implements
  no authentication and injects no credential - the child resolves exactly the
  login an interactive `claude` resolves". Proposed replacement: keep the sentence
  as the default and add a bounded exception: "Exception, declared not inferred:
  when the operator sets the Claude authentication channel to the headless OAuth
  token, the worker injects that token and records the choice in the run's runtime
  identity. No other credential is injected, and `ANTHROPIC_API_KEY` remains
  scrubbed unconditionally." Without this edit the credential clause and D4
  contradict each other.
- `2026-02-25-llm-context-provider-abstraction-adr`, Implementation, **Auth**
  bullet: "the 1-year headless Claude token (`claude setup-token`, validated in
  the original record) remains the Claude method of choice". This is already false
  in force, since 2026-08-02 made subscription login the default. Proposed
  replacement: "The one-year headless token from `claude setup-token` is the
  Claude method of choice for headless profiles, selected by an explicit
  authentication channel; attended profiles default to the operator's own
  subscription login."
- Same record, Implementation, **Agent resolution** bullet. Proposed addition:
  "Resolution yields an absolute path and a recorded runtime authority for every
  launched component, including the provider CLI the adapter drives."
- `2026-08-02-provider-capability-evidence-adr`, Consequences, "The implementation
  must maintain evidence citations and invalidation when runtime identity
  changes". Proposed sharpening: "Runtime identity includes the resolved provider
  binary and its version. A proof is valid only inside the version range it
  declares; a resolved binary outside that range invalidates the proof and the
  record derives `supported`, never `proven`." Without this edit the matrix can
  report `PROVEN` for a binary that never completed a turn.
- `2026-08-02-provider-model-catalog-adr`, Consequences, "Catalogs can vary by
  account, authentication, region, CLI version, and execution mode". Proposed
  addition to the Health or Freeze clause: "A catalog revision records the
  resolved CLI version that produced it, and a revision produced by one binary is
  not served for a lane now resolving a different one."
- `2026-07-18-desktop-product-profile-adr`, Implementation, "Providers resolve
  capsule-owned assets". Proposed sharpening: "Providers resolve capsule-owned
  assets, including the provider CLI the ACP adapter drives. Capsule validation
  requires that asset, and a host CLI or an inherited executable override never
  substitutes for it." Without this edit the constraint reads as satisfied while
  the CLI escapes it.
- `2026-07-21-capsule-install-layout-adr` needs no edit: the CLI is already a
  member of the ACP closure built from `package-lock.json`, and naming it as a
  consumed asset changes no layout or attestation rule.
  `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr` needs no
  edit: no client wire shape changes.
- Policy source `no-unproven-providers-in-served-profiles`, Admission rule.
  Addition, applied through the rules verbs and a sync as part of accepting this
  record: "A lane proof binds to the binary identity that completed the turn. The
  served eligibility encodes the admitted version range, and a resolved binary
  outside it is ineligible exactly as an unproven lane is." This keeps the rule and
  D2 from disagreeing about what proof means.

D4's declared `claude_auth_channel` exception (opt-in `oauth_token`, default
`subscription_login`) is accepted as drafted; the harness-provisioning no-auth clause
edit above is applied accordingly.

Accepted 2026-10-01 under the user's blanket approval of that date.

## Amendment - provider-binary-policy (2026-10-01, managed policy)

The vendored adapter applies the Claude managed-policy settings tier before any session exists, writing its `env` entries into the environment the CLI child inherits; a client cannot suppress it, and passing no setting sources does not (`2026-10-01-provider-binary-policy-audit`, `managed-policy-env-reaches-the-child`). That tier is the operator organisation's own authority over Claude Code on the host, so this record honours it rather than working around the adapter: a served Claude lane runs under whatever managed policy the host carries, and the lane's runtime identity records that a managed tier was present. No source, comment or document of this repository may claim that the lane drops managed configuration.

## Amendment - runtime evidence precision (2026-10-02)

D3's one row stores the first observed provider-native session ID for a run and lane. D5 opens a new native session for each model call, so later session IDs are not enumerated by that row. Later calls must match the stored stable binary, adapter, runtime-authority, and authentication fields or fail before their prompt. A row therefore proves the identity of its first initialized session and the stable identity checks on later sessions; it is not a session history.

The preceding managed-policy amendment establishes that the adapter honors any host managed tier. ACP initialize and session creation do not disclose whether a tier existed or loaded on a particular host. Until a trustworthy host-tier presence signal is available, D3 records `managed_policy_present = null` (unknown), including for Claude. The earlier sentence claiming the row records presence is superseded; capability advertisement alone is not a presence signal.
## Amendment (2026-10-02): capsule authority precedence

The 2026-10-02 integrated review found that the original D1 ordering let an
explicit setting select an external CLI while a desktop capsule was armed,
contrary to the binding capsule-owned runtime constraint. The user authorized
the recommended capsule-first resolution after that finding was presented.
An armed capsule therefore owns the Claude CLI even when an explicit path is
configured. A missing or escaping capsule CLI refuses catalog probing and
construction with a typed runtime-unavailable result; neither the explicit
setting nor any other rung substitutes for it. Outside a capsule, the explicit
absolute setting remains the first rung, including for the pinned Compose
profile. This amendment replaces the conflicting D1 ordering and preserves the
single shared resolver for probe and turn.
