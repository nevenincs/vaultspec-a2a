---
tags:
  - '#plan'
  - '#provider-binary-policy'
date: '2026-10-01'
tier: L2
related:
  - '[[2026-10-01-provider-binary-policy-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-08-02-provider-capability-evidence-adr]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-10-01-provider-binary-policy-acp-adapter-upgrade-research]]'
modified: '2026-10-01'
body_schema: body-v2
body_hash: 'sha256:1afce7edfa6b120b71b397099d5407f70e7a59bc6c69e0b3846f8665fe82992f'
---

# `provider-binary-policy` plan

Make the provider launch identity profile-scoped, proof-bound and recorded, wire the Claude OAuth token behind a declared channel, and delete the resume capability no production path can reach.

## Description

Approved 2026-10-01. Basis: the user's blanket approval of this feature's implementation work, given in session on 2026-10-01, together with acceptance of `2026-10-01-provider-binary-policy-adr` on the same date, including its D4 opt-in `claude_auth_channel` exception. That record's Implementation and Constraints sections are binding on every Step here.

The work answers one question in five parts: what runtime a served turn runs as, and what the service can later prove about it. Today the lock-vendored Claude CLI and the one on this host's PATH are different builds, an armed desktop capsule owns Node and the ACP adapter but not the CLI that does the work, no run records which binary produced it, the declared OAuth token setting is read by no production code while a test prerequisite counts it as a credential, and a provider session carries an unreachable resume branch. Grounding is `2026-10-01-provider-binary-policy-research` and the findings `claude-binary-split`, `capsule-claude-binary-still-overridden-by-path`, `no-cli-version-identity`, `oauth-token-setting-unwired` and `per-call-provider-sessions` in `2026-09-24-architecture-review-audit`, both inherited through the governing record.

Decision coverage. Every Step executes authority that is already accepted, so no new ADR is needed and none is proposed here:

- `2026-10-01-provider-binary-policy-adr` governs the whole plan, one commitment per Phase: D1 is P01, D2 is P02, D3 is P03, D4 is P04, D5 is P05.
- `2026-07-15-agent-harness-provisioning-adr` governs P01 through its stack-identity clause and P04 through its no-credential clause, under the declared-channel exception accepted with D4.
- `2026-08-02-provider-capability-evidence-adr` governs P02: a proof is valid only inside the runtime identity it was earned on.
- `2026-07-18-desktop-product-profile-adr` governs P01.S01, P01.S02 and P01.S04, where the capsule's immutability promise reaches the provider CLI.

Scope limits. The ACP wire contract, the permission model, the durable event log and the continuation model keep their current owners. Disclosing runtime identity on the dashboard edge is deferred by the governing record as a cross-repository contract event and is not planned here. The reconciliation edits that record proposes to other ADRs and to the policy source `no-unproven-providers-in-served-profiles` belong to those records' owners and to the user's rules verbs; no Step in this plan edits a decision record or a policy source.

Concurrency with other work. An executor is landing P06.S46 of `2026-09-24-architecture-review-plan` in `src/vaultspec_a2a/providers/_claude_tool_policy.py` and other provider residual fixes; no Step here owns that file. Other plans add database migrations at the same time, so P03.S11 names its migration by purpose and its revision and down-revision ids are assigned at execution, in the order the file merges with the heads then present.

## Steps

### Phase `P01` - One resolver owns the Claude binary

Exactly one seam answers which CLI a Claude or Z.ai child will run, the answer is an absolute path chosen by the profile's authority order, and an armed desktop capsule owns that asset exclusively.

- [ ] `P01.S01` - Add the capsule-owned Claude CLI path authority beside the existing Node and ACP authorities, selecting the libc variant by the rule the adapter uses; `src/vaultspec_a2a/providers/_factory_commands.py`.
- [ ] `P01.S02` - Require the capsule Claude CLI as a third validated capsule asset so an armed desktop profile refuses to arm without it; `src/vaultspec_a2a/desktop/profile.py`.
- [ ] `P01.S03` - Declare the absolute-path claude_cli_executable setting as the explicit top rung and resolve it with the other path settings; `src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/control/config.py, .env.example`.
- [ ] `P01.S04` - Rewrite pin_claude_executable into the profile-scoped authority order returning the absolute path and the rung that answered, with an armed capsule exclusive and fail-loud over an inherited executable override, and update the served-turn and catalog-probe call sites; `src/vaultspec_a2a/providers/cli_resolution.py, src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/factory.py`.
- [ ] `P01.S05` - Refuse a served Claude or Z.ai launch and the Claude catalog probe when no rung resolves a CLI, with a typed runtime-unavailable reason instead of an unpinned child; `src/vaultspec_a2a/providers/factory.py, src/vaultspec_a2a/providers/cli_resolution.py`.
- [ ] `P01.S06` - Install one exact Claude CLI version in the Compose worker image and name it to the service through the new setting; `service/docker/prod.Dockerfile, service/docker-compose.prod.yml`.
- [x] `P01.S17` - Bump the vendored Claude ACP adapter to its latest release and re-prove the protocol surface the ACP layer depends on; `package.json, package-lock.json, src/vaultspec_a2a/graph/tests/acp_simulator.py, src/vaultspec_a2a/providers/`.

### Phase `P02` - Proof-bound version ranges at the eligibility service

A lane proof declares the binary identity and version range it covers, and a resolved binary outside that range makes the lane ineligible with a typed reason that presets-list and launch both read.

- [ ] `P02.S07` - Give LaneProof the binary, proved version, floor, and exclusive ceiling its live test covers, and record those values for the claude, codex, and zai entries from reruns against the binaries in force; `src/vaultspec_a2a/providers/lane_admission.py`.
- [ ] `P02.S08` - Add a binary version probe that reads a resolved launcher's reported version once per launch identity, memoized per process, and derive the admitted range as exact equality for the pinned rungs and floor to next minor for the host PATH rung; `src/vaultspec_a2a/providers/binary_version.py, src/vaultspec_a2a/providers/lane_admission.py`.
- [ ] `P02.S09` - Make an out-of-range resolved binary a typed lane ineligibility so presets-list omits the lane and provider construction refuses it; `src/vaultspec_a2a/providers/provider_catalog_service.py, src/vaultspec_a2a/providers/factory.py`.
- [ ] `P02.S10` - Pin the CI Codex install to an exact version, verify its npm signatures, and make that version the codex lane proved version; `.github/workflows/test.yml, src/vaultspec_a2a/providers/lane_admission.py`.

### Phase `P03` - Recorded runtime identity per run and lane

Every run durably records the adapter, CLI, authority, auth mode, and provider-native session id that produced it, before any claim about that run's behaviour is made.

- [ ] `P03.S11` - Add the provider runtime identity table, its model, and its repository, naming the migration by purpose and assigning its revision and down-revision ids at execution time in the order it merges with the migrations other plans land concurrently; `src/vaultspec_a2a/database/migrations/versions/, src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/runtime_identity_repository.py, src/vaultspec_a2a/database/__init__.py`.
- [ ] `P03.S12` - Add the runtime identity port, its worker SQL adapter, and its graph-compile injection beside the cost port; `src/vaultspec_a2a/graph/protocols.py, src/vaultspec_a2a/worker/runtime_identity_port.py, src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P03.S13` - Capture provider, catalog key, runtime authority, adapter name and version, adapter entry path, CLI path and version, Node version, auth mode, and provider-native session id at a lane first successful initialize, and write one row per run and lane while keeping the existing INFO line; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_model_state.py, src/vaultspec_a2a/graph/nodes/worker.py`.

### Phase `P04` - The Claude authentication channel is declared, not inferred

A new channel setting decides whether the worker injects the headless OAuth token, an empty token under that channel refuses the lane, and the honesty defects that advertised an unwired token close with it.

- [ ] `P04.S14` - Add the claude_auth_channel setting defaulting to subscription_login, inject the configured token into the child as CLAUDE_CODE_OAUTH_TOKEN only under oauth_token, refuse the lane when that value is empty, and record the auth mode the run used; `src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/providers/factory.py`.
- [ ] `P04.S15` - Probe the production credential resolution in the Claude test prerequisite instead of the settings value, and state in the example environment that a dotenv-only token authenticates nothing outside the declared channel; `src/vaultspec_a2a/conftest.py, .env.example`.

### Phase `P05` - Unreachable provider-session resume removed

The session/load branch and the session id option no production path can reach leave the code, and per-call sessions stay the only shape.

- [ ] `P05.S16` - Remove the unreachable session/load branch and the session id option, and prove no production caller sets a provider session id; `src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/acp_chat_model.py`.

### Phase `P06` - adapter release enrolment

Take up what the newer vendored adapter offers this lane, as the upgrade research found it, without a new decision.

- [ ] `P06.S18` - Carry the per-model token usage the adapter now reports on each prompt result into the turn's usage metadata; `src/vaultspec_a2a/providers/_acp_protocol.py, src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_types.py`.
- [ ] `P06.S19` - Handle or log every session update kind the adapter emits, including usage, config option and session info updates; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_protocol.py`.
- [ ] `P06.S20` - State and record that the adapter's managed-policy tier reaches the provider child, correcting the claim that no setting sources drops managed configuration; `src/vaultspec_a2a/providers/_claude_tool_policy.py, src/vaultspec_a2a/providers/_acp_session.py`.

## Parallelization

P05.S16 lands first, alone. It only deletes, and it clears `src/vaultspec_a2a/providers/acp_chat_model.py` and `src/vaultspec_a2a/providers/_acp_session.py` for every Step that follows.

Three owners then run concurrently, with disjoint write ownership:

- Owner A - P01.S01, P01.S02, P01.S03, P01.S04, P01.S05, P01.S06, in that order. Owns `src/vaultspec_a2a/providers/cli_resolution.py`, `src/vaultspec_a2a/providers/_factory_commands.py`, `src/vaultspec_a2a/providers/factory.py`, `src/vaultspec_a2a/providers/acp_chat_model.py`, `src/vaultspec_a2a/desktop/profile.py`, `src/vaultspec_a2a/control/infra_config.py`, `src/vaultspec_a2a/control/config.py`, `.env.example` and `service/docker/`.
- Owner B - P02.S07, P02.S08, P02.S10, in that order. Owns `src/vaultspec_a2a/providers/lane_admission.py`, `src/vaultspec_a2a/providers/binary_version.py` and `.github/workflows/test.yml`.
- Owner C - P03.S11 then P03.S12. Owns `src/vaultspec_a2a/database/`, `src/vaultspec_a2a/graph/protocols.py`, `src/vaultspec_a2a/graph/compiler.py` and `src/vaultspec_a2a/worker/`.

Four Steps join those owners' files and are therefore serial, in this order, after the owner that held each file has finished with it:

- P02.S09 after P01.S04 and P02.S08; it writes `src/vaultspec_a2a/providers/factory.py` and `src/vaultspec_a2a/providers/provider_catalog_service.py`.
- P04.S14 after P01.S05 and P02.S09; it writes `src/vaultspec_a2a/control/infra_config.py` and `src/vaultspec_a2a/providers/factory.py`.
- P04.S15 after P04.S14; it writes `.env.example`, which Owner A last held at P01.S03.
- P03.S13 after P01.S04, P03.S12 and P04.S14; it writes `src/vaultspec_a2a/providers/acp_chat_model.py`, `src/vaultspec_a2a/providers/_acp_model_state.py` and `src/vaultspec_a2a/graph/nodes/worker.py`, and it records the auth mode P04.S14 decides.

Hard ordering beyond that: P01 precedes P02.S09, P03.S13 and P04 because each consumes the resolver's answer and the rung that produced it. Owners B and C have no dependency on each other. Each owner commits its own Steps; with one shared worktree the owners serialize their commits, and with separate worktrees they merge in the order above.

## Verification

Each Step carries a real-behaviour test that fails before the change and passes after it. No mocks, no monkeypatching: a capsule tree is a real directory with real executable files, a version probe runs a real subprocess, a database assertion round-trips through a real database, and an environment assertion is read off a real child process.

Plan-level criteria:

- `just ci` is green on each Step's commit, and `just ci-merge` is green for the pull-request profile.
- A capsule tree whose Claude CLI asset is absent refuses to arm, naming the missing path (P01.S02).
- A capsule tree whose Claude CLI asset is present is the path a served launch resolves, with a different `claude` earlier on the service's own PATH and a `CLAUDE_CODE_EXECUTABLE` already set in the child environment (P01.S01, P01.S04).
- A resolution that reaches no rung refuses the launch and the catalog probe with a typed reason, and never hands the adapter an unpinned child (P01.S05).
- A lane whose resolved binary reports a version outside its proof range is absent from `presets-list` and refused at provider construction, and the same lane in range is served (P02.S08, P02.S09).
- The migration upgrades and downgrades cleanly from the head present at merge time, on both the SQLite and Postgres backends (P03.S11).
- A completed turn writes exactly one runtime identity row per run and lane, carrying the CLI version the same resolved binary reports when asked directly (P03.S13).
- Under `subscription_login` the child environment carries no token derived from settings, and an operator's ambient export still reaches the child; under `oauth_token` with an empty setting the lane refuses rather than running unauthenticated (P04.S14).
- The Claude credential prerequisite agrees with the production resolution on a host with no token set (P04.S15).
- No production caller sets a provider session id, proven over the source tree (P05.S16).

Credential limits on this host. No live provider credentials are available here, so the following Steps are proven only up to the binary boundary: P01.S01, P01.S02, P01.S04, P01.S05, P01.S06, P02.S08, P02.S09, P04.S14 and P04.S15. Their tests spawn real binaries, real capsule trees and real stub launchers that report versions, and they assert the environment and the refusal a real child would receive; none of them completes a model turn. Two Steps cannot be finished here at all and must run on a credentialed host before the plan closes: P02.S07, because a proof moves only by rerunning its cited live test against the binary in force and recording that version by hand, and P03.S13, whose criterion is a completed live turn writing its identity row. Until those two reruns happen, the recorded `proved_version` values are provisional and must be reported as pending verification rather than as proof.

Review follows the vaultspec system section: one review at each Phase close, one at plan close, and one before handoff for merge, with coincident gates sharing a single integrated review.
