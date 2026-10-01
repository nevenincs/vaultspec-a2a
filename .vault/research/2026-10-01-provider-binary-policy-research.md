---
tags:
  - '#research'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:6a01931c9a71c2308200b19e8465cfda77daf99cd2c3ae7893ee71d9455c13f8'
related:
  - "[[2026-09-24-architecture-review-audit]]"
---

# `provider-binary-policy` research: `which provider binary a served turn runs, how its identity is proved, and whether provider sessions are reused`

The service admits a provider lane to service only after a real turn completed on
it, but nothing binds that admission to the binary that completed it. This record
gathers the evidence needed to decide five coupled questions: which Claude binary
each served profile runs, what version range a lane proof covers, what runtime
identity a run records, whether the declared `CLAUDE_CODE_OAUTH_TOKEN` setting is
wired into the child, and whether provider-native sessions are resumed. Findings
are from this checkout at `2026-10-01`, from live probes on this host, and from
current vendor documentation fetched the same day. The evidence favours
profile-scoped binary authority with a recorded, range-checked identity; it does
not settle the credential channel, which trades headless reach against the
provider layer's no-credential contract.

## Findings

### One resolver now serves both the probe and the turn, but it resolves from the service PATH and has no capsule branch

`pin_claude_executable` takes an existing `CLAUDE_CODE_EXECUTABLE` value, else the
first absolute PATH directory of the SERVICE environment carrying `claude`, else
returns `None` and leaves the adapter on its vendored binary
(`src/vaultspec_a2a/providers/cli_resolution.py:111-131`). Both the served turn
(`src/vaultspec_a2a/providers/acp_chat_model.py:354-355`) and the catalog probe
(`src/vaultspec_a2a/providers/factory.py:200-215`) call it, so the discovery and
execution split is closed. The resolver has no desktop-capsule branch, unlike the
Node runtime and the ACP adapter, which under a configured capsule root resolve
ONLY from capsule assets and raise when absent
(`src/vaultspec_a2a/providers/_factory_commands.py:227-258,302-311`). A served
desktop turn therefore runs capsule Node plus the capsule adapter driving a PATH
`claude`. Recorded as `capsule-claude-binary-still-overridden-by-path` and
`claude-binary-split` in `2026-09-24-architecture-review-audit`.

### The capsule's own validation cannot see the gap, because the CLI is not a capsule asset

Capsule validation checks exactly two files, the Node executable and the ACP
entry, and checks only that each is a file
(`src/vaultspec_a2a/desktop/profile.py:313-335`). The capsule root reaches the
provider seam through `settings.capsule_assets_root`
(`src/vaultspec_a2a/control/infra_config.py:296-307`), whose description already
states the intent the CLI breaks: "the provider factory resolves the default Node
executable and ACP entry point ONLY from this root, with no checkout or PATH
fallback".

### The lock vendors a complete Claude CLI, integrity-pinned, and it is 79 patch releases behind this host

`package-lock.json` (lockfileVersion 3) pins
`@agentclientprotocol/claude-agent-acp@0.59.0` and
`@anthropic-ai/claude-agent-sdk@0.3.207` with its per-platform binary packages,
each carrying a `sha512` integrity hash; the installed
`node_modules/@anthropic-ai/claude-agent-sdk-linux-x64/claude` is a 259 MB native
executable, `sha256:85e7e988a392d859f90802ca21fb26e89d3c9ab527f5ed0b08df3955e34d5c83`
on this checkout. The adapter prefers `CLAUDE_CODE_EXECUTABLE` and otherwise
resolves that package by libc variant
(`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:161-196`).
Live on this host: the vendored binary reports `2.1.207 (Claude Code)` and the
PATH binary at `/opt/node22/bin/claude` reports `2.1.286 (Claude Code)`. The audit
measured 2.1.207 against 2.1.281 one week earlier, so the host binary moved 5
releases in a week while the vendored one is frozen until a lock bump.

### The capsule supply chain already has the shape a vendored CLI needs

`2026-07-21-capsule-install-layout-adr` builds the ACP closure from the committed
`package-lock.json`, projects each verified tarball verbatim into its nested
`node_modules` destination, and publishes a descriptor digest as generation
evidence; the committed, human-reviewed lock is the supply-chain trust root.
`2026-07-18-desktop-product-profile-adr` already states that providers resolve
capsule-owned assets. Adopting the vendored CLI as a capsule asset therefore adds
a path, not a trust model.

### Upstream supports exact version pinning, update suppression, and signed release artifacts

Claude Code's native installer accepts an exact version
(`curl -fsSL https://claude.ai/install.sh | bash -s 2.1.89`); native installs
otherwise auto-update in the background. Updates are suppressed with
`DISABLE_AUTOUPDATER=1` in a settings `env` block, or completely with
`DISABLE_UPDATES`, which the documentation recommends "when you distribute Claude
Code through your own channels and need users to stay on the version you
provide". A version range is enforceable from settings: `autoUpdatesChannel`
(`latest` or `stable`), `minimumVersion` as an update floor, and the managed
settings `requiredMinimumVersion` and `requiredMaximumVersion`, which make the CLI
refuse to START outside the range. Each release publishes a `manifest.json` of
per-platform sha256 checksums signed with the Anthropic GPG key whose fingerprint
is `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE`, with signatures available from
2.1.89 onward; Linux binaries carry no individual code signature. The npm package
`@anthropic-ai/claude-code` installs the same native binary through a per-platform
optional dependency and does not run on Node at runtime.
https://code.claude.com/docs/en/setup

### Codex publishes several versions a day, pins its platform binaries exactly, and carries registry attestations; this repository installs it unpinned

The npm registry reports `@openai/codex@0.159.3` as `latest`, published
`2026-09-30T23:02:02Z`, with 5142 published versions, platform binaries declared
as exact-version optional dependencies (`npm:@openai/codex@0.159.3-linux-x64` and
siblings), and a `dist` object carrying both `signatures` and `attestations`
(https://registry.npmjs.org/@openai/codex). `.github/workflows/test.yml:223` runs
`npm install -g @openai/codex` with no version. npm documents
`npm audit signatures` as the command verifying registry signatures and provenance
attestations https://docs.npmjs.com/generating-provenance-statements. OpenSSF
Scorecard's Pinned-Dependencies check requires dependencies declared at specific
versions or hashes, for reproducibility and to blunt compromised-dependency and
dependency-confusion attacks, and names inhibited security updates as the
accepted cost https://github.com/ossf/scorecard/blob/main/docs/checks.md.

### A lane proof names a test, never a binary, and nothing durable records which binary ran

`LaneProof` carries exactly `test` and `proves`
(`src/vaultspec_a2a/providers/lane_admission.py:112-122`), and the declaration
admits Claude, Codex, and Z.ai on that basis (`:167-205`). At session setup the
service logs one INFO line with the adapter's `agentInfo` name and version and the
resolved CLI path (`src/vaultspec_a2a/providers/acp_chat_model.py:416-439`,
reading `src/vaultspec_a2a/providers/_acp_session.py:496-500`); the CLI's own
version is never probed, and the line is a log, not a run record. The durable
run-side execution authority is the frozen team assignment, a schema-versioned,
digest-bearing structure served on the dashboard edge
(`src/vaultspec_a2a/api/schemas/gateway.py:261-286`), which carries provider,
execution mode, catalog revision, and model but no runtime identity. Cost: a
`--version` probe of the 259 MB vendored binary took 0.22 s on this host and a
sha256 of it took 1.9 s, so a per-launch version probe is affordable and a
per-launch digest is not without caching.

### The OAuth token setting is declared and allowlisted but never read, and injecting it would change which identity a turn runs as

`claude_code_oauth_token` is declared with aliases
`VAULTSPEC_A2A_CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_OAUTH_TOKEN`
(`src/vaultspec_a2a/control/infra_config.py:508-513`). No production code reads
it: the only readers are the test prerequisite probe
(`src/vaultspec_a2a/conftest.py:178`) and live tests. Separately, the child
environment builder scrubs every `CLAUDE_CODE_*` name except a four-entry
allowlist that includes the token and `CLAUDE_CODE_EXECUTABLE`
(`src/vaultspec_a2a/workspace/environment.py:146-161`), so a token exported into
the SERVICE process environment does reach the child while a token supplied only
through `.env`, which loads into settings, does not. The prerequisite probe counts
the settings value, so the probe passes where the production child would be
unauthenticated. Upstream places `CLAUDE_CODE_OAUTH_TOKEN` fifth in authentication
precedence, above the `/login` subscription credential at rank seven, so an
injected token REPLACES the operator's interactive login for that session; the
token is created by `claude setup-token`, lasts one year, requires a Pro, Max,
Team, or Enterprise plan, can only make model requests, and is not read in bare
mode https://code.claude.com/docs/en/authentication. The Compose worker carries no
provider credential at all (`compose-provisions-no-lane` in
`2026-09-24-architecture-review-audit`), so a headless container lane has no other
credential path.

### Both upstreams now document session resume and fork; the local transcript is same-machine and outside this service's retention control

Claude's SDK documents `resume` by session id, `fork_session`, and `continue`,
with transcripts written to `~/.claude/projects/<encoded-cwd>/*.jsonl` or under
`CLAUDE_CONFIG_DIR`, resumable only on the machine that wrote them unless a
`SessionStore` adapter mirrors them, and it recommends capturing results as
application state as the more robust alternative to shipping transcripts
https://code.claude.com/docs/en/agent-sdk/sessions. Codex exposes `thread/resume`
and `thread/fork`, the latter copying stored history, with a warning and a
one-time model-switch instruction when a resumed thread is given a different model
https://learn.chatgpt.com/docs/app-server. In this service a session is created
per model call: `setup_session` runs after every spawn
(`src/vaultspec_a2a/providers/acp_chat_model.py:540-570`), the `session/load`
branch exists but is reached only when `config.session_id` is set
(`src/vaultspec_a2a/providers/_acp_session.py:744-745`,
`src/vaultspec_a2a/providers/acp_chat_model.py:134-136`), and no production caller
sets it, so the branch has never run in production. The LangGraph checkpoint is
therefore the only transcript, which is what makes recovery and forking
provider-agnostic, at the cost of re-sending the full transcript and one spawn per
call (`per-call-provider-sessions` in `2026-09-24-architecture-review-audit`).

### What the evidence does not settle

The credential channel is a value judgment between headless reach and the
provider layer's no-credential contract, recorded in the 2026-08-02 amendment of
`2026-07-15-agent-harness-provisioning-adr`; the evidence shows only that the
current state is neither. Nothing here was probed on Windows or macOS, no capsule
was built or armed, no live turn was run on the vendored binary, and the Kimi and
Antigravity lanes were not re-examined beyond the audit's findings. Whether a
resumed provider session would measurably reduce cost was not measured, because
the ACP lane reports no token usage (`token-accounting-gaps` in the same audit).

## Sources

- `src/vaultspec_a2a/providers/cli_resolution.py:111-131`
- `src/vaultspec_a2a/providers/acp_chat_model.py:134-136,354-355,416-439,540-570`
- `src/vaultspec_a2a/providers/factory.py:200-215`
- `src/vaultspec_a2a/providers/_factory_commands.py:227-258,302-311`
- `src/vaultspec_a2a/providers/_acp_session.py:496-500,744-745`
- `src/vaultspec_a2a/providers/lane_admission.py:112-122,167-205`
- `src/vaultspec_a2a/desktop/profile.py:313-335`
- `src/vaultspec_a2a/control/infra_config.py:296-307,508-513`
- `src/vaultspec_a2a/workspace/environment.py:146-161`
- `src/vaultspec_a2a/conftest.py:178`
- `src/vaultspec_a2a/api/schemas/gateway.py:261-286`
- `node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:161-196`
- `.github/workflows/test.yml:223`
- `package-lock.json`, `@anthropic-ai/claude-agent-sdk@0.3.207`,
  `@agentclientprotocol/claude-agent-acp@0.59.0`
- https://code.claude.com/docs/en/setup
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/agent-sdk/sessions
- https://learn.chatgpt.com/docs/app-server
- https://registry.npmjs.org/@openai/codex
- https://docs.npmjs.com/generating-provenance-statements
- https://github.com/ossf/scorecard/blob/main/docs/checks.md
- Live probes on this host, 2026-10-01: vendored `claude --version` reported
  `2.1.207 (Claude Code)`; PATH `/opt/node22/bin/claude --version` reported
  `2.1.286 (Claude Code)`; `sha256sum` of the vendored binary took 1.9 s.
