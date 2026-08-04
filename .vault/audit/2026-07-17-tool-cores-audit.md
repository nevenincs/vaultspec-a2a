---
tags:
  - '#audit'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-08-02'
body_hash: 'sha256:1f1bd29c64d30fc152bfa5e831548d19bb675e70e0c9b1ff63af932b304d7e20'
related:
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-07-17-tool-cores-plan]]"
  - "[[2026-07-17-tool-cores-dedup-audit]]"
---

# `tool-cores` audit: `S24 holistic safety and intent gate`

## Scope

The mandatory P05.S24 review gate over ALL landed tool-cores changes on main
(commit range `e50b88e..8b83f77`, tool-cores commits): P01-P05 implementation,
the P04 credential-cleanup fix, the codexwire harness-wiring defect fix, both
provider config-home modules, the registry/compose seam, the worker composition
site, presets and personas, and the exec/audit records — verified against
current file state on main, not only the per-branch diffs previously PASSed.
Reviewed by the team's dedicated code-review persona; verdict returned
2026-07-17 and persisted here verbatim in substance.

## Findings

**STATUS: PASS** — with the usage-gated live re-arms (`P01.S05`/`P03.S16`
Claude ~2026-07-20, `P04.S20`/`P04.S21` Codex ~2026-07-23) as honestly
recorded opens, and `P05.S25` reconciliation owed after this gate. No CRITICAL
or HIGH findings.

### Safety — read-only boundary, credential hygiene, isolation (clean)

- No write verb is composable on either lane: the registry holds exactly one
  entry (`vaultspec-rag`, `read_only: True`, three read tools); the
  write-capable vaultspec-core MCP and the rag `reindex_*` verbs are omitted
  by construction. The `_require_read_only` trust-root guard fires on BOTH
  transports (`src/vaultspec_a2a/providers/_acp_mcp.py:137` Claude home,
  `:179` Codex specs) so registry drift fails loud. Codex `enabled_tools` is
  an exact read-tool allowlist.
- The `.vault` write-deny is untouched; every live proof asserts zero
  agent-origin document-dir writes.
- Credential hygiene: the Claude isolated home is ZERO-credential (only
  `.claude.json`; auth rides env); the Codex home copies file-based
  `auth.json` owner-only (0o700 dir, 0o600 file) with single-turn lifetime,
  and the HIGH-1 fix places the home build INSIDE the streaming try
  (`src/vaultspec_a2a/providers/codex_chat_model.py:366`) with cleanup in the
  finally (`:429`) plus builder self-clean — every catchable failure reclaims
  the credential copy; only bounded, owner-only, prefix-tagged SIGKILL residue
  remains, honestly recorded.
- Isolation: both lanes redirect to a worker-owned config dir
  (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`) carrying exactly the declared read-only
  servers; ambient operator MCP suppressed; no leak-back; cleanup on both
  paths.

### Intent — ADR decisions to landed code (no drift)

Every ADR decision has landed code or an honest open: the native read floor;
the mandatory adapter migration (deprecated pin retired) with regression
verification and the S20 re-probe; the ambient-suppression home built
regardless of the re-probe; the allowlist union closing the attach-combined
gap; preset opt-in and persona truth; the surfacing contingency correctly
triggered on the NOT-SURFACED verdict and live-verified SURFACES; the Codex
leg over the same registry; the vaultspec-core MCP correctly omitted. The
three unplanned commits each trace to an ADR-sanctioned path: the Docker
cross-libc fix serves the mandated migration, the harness-provisioning ADR
amendment is the ADR's own conditional clause firing, and the codexwire fix
completes the Codex leg after `P04.S21` discovered the production threading
was structurally dead (the direct-field tests had masked it — the masking
lesson is recorded in the `P04.S18` exec record).

### Completeness — opens are honest

Nineteen implementation and hygiene steps closed on reviewer-PASSed landed
evidence. The six opens at gate time were all honestly gated, none reported
as passing: `P01.S05` + `P03.S16` armed as parameter swaps of the green Z.ai
harness, blocked on the Claude weekly usage window; `P04.S20` + `P04.S21`
blocked on the Codex usage window (the wiring fix that must precede `S21` is
landed), each with a one-command re-arm; `S24` is this gate; `S25` follows.

### Evidence chain (spot-checked)

`P02.S09` NOT SURFACED is dispositive with a positive control; `P03.S14`
SURFACES is corroborated by the live `P03.S17` green (run `pw7-1784282060`)
whose server-side rag-daemon `POST /search` access-log evidence (400 then 200,
`service.search event=completed`, in-window) cannot be fabricated by native
tools; zero document writes across proofs.

### Residual unknown (correctly open)

Whether Codex ADMITS an MCP call at runtime under `approval_policy: "never"` +
`sandbox: "read-only"` + per-tool `approval_mode: "auto"` (the undocumented
axis composition) is held open under `P04.S21`, not asserted.

## Recommendations

Proceed to `P05.S25` reconciliation; execute the four usage-gated proofs when
the provider windows reset (Claude ~2026-07-20 08:00, Codex ~2026-07-23
06:15) using the one-command re-arms in their exec records; keep
`P01.S05`/`P03.S16`/`P04.S20`/`P04.S21` open until their green runs exist.
Carry forward the corroboration posture for semantic proofs (daemon-log
evidence recorded in exec records, disclosed as a non-test surface) and the
masking-gap lesson (never prove wiring by constructing states production
cannot reach).

### Web-grounding execution sweep (2026-08-01, P01) - one finding, open

Raised during Phase `P01` of the web-grounding plan, by the Step that split the
registry trust root rather than by a review pass.

- `unexercisable-trust-root-guards` (low, open) - the registry's fail-loud trust
  assertions cannot be made to fire by any legitimate test, and this predates
  the Step that found it. The registry is closed by design, with no plugin or
  discovery machinery, so no production input can present an undeclared entry to
  either composition seam. Removing the newly added egress assertion from the
  seam breaks zero tests; removing the pre-existing read-only assertion breaks
  zero tests either. A fail-loud guard that no production input can reach is
  documentation rather than enforcement. The Step deliberately kept both, and
  moved the enforceable half to a registry construction seam that refuses an
  undeclared entry at import, making such an entry unconstructible rather than
  merely unsurfaceable - which is the stronger property. So nothing is broken
  and nothing needs fixing today. It is recorded because the module has carried
  an unprovable guard since before this work, because the same reasoning will
  apply to every future assertion placed at that seam, and because the honest
  reading is that the constructor is the enforcement and the seam guards are
  redundancy. Anyone later tempted to prove the seam guards by monkeypatching
  the registry or adding an injection parameter with no production caller should
  read this entry first: both were considered and refused here.

- `discovery-retry-tests-fail-against-a-live-engine` (low, open, not this
  feature's to fix) - two retry tests in the authoring discovery suite assert
  that no engine resolves, and fail on any machine where one is actually
  listening on the discovery endpoint. Every executor in this Phase hit them and
  each independently attributed them by socket probe rather than assertion,
  which is the right instinct but is wasted effort repeated three times. The
  omission looks unintentional rather than deliberate: a sibling test in the
  same file carries an explicit hedge comment about development machines
  resolving the machine-global candidate, and these two do not. They predate
  this work and are unrelated to it. Recorded here because they will redden the
  authoring suite for anyone reviewing or extending this feature and read as
  fallout from it, which they are not. The fix belongs to whoever owns that
  suite: hedge the two tests the way their sibling already is, or bind them to a
  port no development engine claims.

### Web-grounding P01 review (2026-08-01) - PASS, no blocker

Formal review of the three contract-seam Steps. No critical or high finding; the
Phase landed. Four findings carried forward, two of which are the same decision
seen from different sides.

- `web-locator-producer` (medium, open) - the typed channel has no production
  emitter. The research producer returns an empty locator list unconditionally,
  its own docstring deferring extraction to a later refinement, so the contract
  admits a shape nothing produces and the submit refusal cannot fire in a real
  run. Both Steps closed honestly on the acceptance conditions their rows state,
  through the real injection seam - this is a plan gap, not an execution defect.
  The later live-proof Step requires a real retrieval landing as a typed locator
  and cannot pass without an extractor. Now assigned as a new Step in the
  delivery Phase.
- `refusal-has-no-revision-route` (medium, open) - branch-side locator
  validation raises out of the researcher node, and that node is wired with no
  retry policy unlike every sibling in the topology. Latent only because of the
  finding above: once an extractor lands, a model-produced locator one character
  over the excerpt cap, carrying an extra key, or missing a scheme aborts the
  whole run instead of routing into the revision loop - and a retry would not
  help, the failure being deterministic. Folded into the same new Step, because
  deciding whether the producer clamps or the branch refuses resolves both.
- `disclosure-scope-vs-record` (medium, open) - the submit refusal is scoped to
  research documents while the governing record states the rule unconditionally
  and the originating Step row repeats it unqualified. The narrowing is sound
  and currently harmless, since the only topology using the researcher fan-out
  accumulates all findings before the research gate. But code and record now
  disagree, which is the drift class this campaign exists to close, so the
  record needs amending rather than the code reverting.
- `unreachable-trust-guards` (medium, open) - independently confirmed and
  already recorded above; the review verified the property extends to the
  pre-existing guard by tracing every registry reference and both call sites.

The review also corrected a claim this campaign had itself recorded. The
research-only scoping was partly justified on the grounds that a later document
would have nowhere sanctioned to put a URL and so could not comply. That is
false: a bare URL in prose is refused by nothing, because the markdown-link
check deliberately exempts web targets. The scoping stands on the one-home
convention alone. The code comment and the Step Record have both been corrected;
the overstatement is noted here because it was authored by this campaign rather
than inherited, and a wrong reason recorded confidently is the same defect class
as a docstring asserting an invariant it does not hold.

Five low findings are recorded in the review and not repeated here: a mutable
public egress catalog where a read-only mapping would match its role, a raw
substring disclosure match with two accept-direction false negatives, an
unlabelled parse error on a malformed authority, a state-schema constant living
in a node module, and the delivery-seam parameter landed one Phase early - the
last being required by its own Step's acceptance condition rather than drift.

- `codex-temp-home-refuses-path-aliases` (low, open, pre-existing) - every Codex
  run already emits a warning that it could not create PATH aliases, because it
  refuses to place helper binaries under a temporary directory and the per-run
  configuration home is created under the operating system temp tree by default.
  Surfaced by live verification against the installed binary during the
  web-grounding delivery Phase, not by any Step's own work. Nothing in the
  current lane depends on those aliases, so the run proceeds - the warning is
  honest rather than spurious. Recorded because it is noise on every Codex run
  that a reader will eventually investigate, and because the desktop profile
  already declares an accounted temporary-home root for exactly this class of
  reason; pointing the Codex home at that root would likely silence it. Belongs
  to whoever owns the config-home layout rather than to this feature.

- `codex-web-search-is-invisible-to-prompt-input` (informational, closed by
  recording) - the tool's debug prompt-input output is byte-identical across all
  four web-search modes, established by running the real binary rather than
  inferred. Web search is a server-side tool and never appears in the
  model-visible prompt input, so no prompt-input assertion can prove that search
  surfaced or was invoked on that lane. Recorded because it removes the cheapest
  activation probe available and would otherwise have been rediscovered by
  whoever takes the live-proof Step, which has been amended to say so. The
  general lesson generalizes past this lane: for a server-side provider tool,
  absence from the prompt is not evidence of absence from the turn.

### Correction to `unexercisable-trust-root-guards` (2026-08-01, S14 delivery)

The finding as first recorded treated the two seam assertions as one class and
said neither could be reached by legitimate production input. That is wrong
about one of them, and the distinction is the whole point.

The construction seam validates that a trust axis was DECLARED - that the key is
present and boolean. It deliberately does not constrain WHAT was declared. So an
entry declaring no local-write protection is perfectly constructible, and the
read-only assertion is the only thing deciding whether such an entry may reach a
surfacing config. It is enforcement, not redundancy. It cannot fire against
today's registry solely because the single shipped entry declares protection;
a second entry declaring otherwise would trip it immediately, with no code change
and no weakening of the freeze. Deleting it - which the original finding invited
as an option - would have removed live enforcement of a policy nothing else
decides.

The egress assertion genuinely is redundant, and remains so: it applies the same
predicate to the same values the constructor already refused, and with the
registry now frozen no path exists to introduce an entry after construction. It
is kept as a cheap backstop against a future second registry or a construction
path that bypasses the declared seam, and its docstring now says exactly that.

Both are kept, for different reasons, and the module no longer implies the seams
are the enforcement when the constructor is. The premise was proven rather than
argued: a test drives the real constructor with an unprotected entry and shows it
is admitted, which is what makes the reachability claim checkable instead of
asserted. No injection parameter and no registry patching were introduced to
force the guard end-to-end - both were considered and refused when the original
finding was recorded, and that refusal was honoured.

Recorded as a correction rather than an edit because the original was authored by
this campaign. A finding that conflates two mechanisms is the same defect class
as code that does, and it is worth the same visibility.

### Post-merge dropped-symbol audit (2026-08-01) - clean beyond the known set

The `feature/agent-flow` merge resolution took the ours side while keeping the
incoming tests, dropping symbols whose callers survived. Four surfaced as type
diagnostics; a fifth was invisible to every static gate because its consumer
reached it dynamically, and would have refused every harness-armed run on one
provider lane while the tree stayed green. That fifth one is why this audit
exists: the type checker had demonstrably failed to bound the class.

Two invisible classes were swept and both are clean.

Presets and rules were checked by LOADING every shipped preset through the
production loader rather than by reading them - a preset naming a dropped agent,
role, or capability fails at load, not at import, so no static gate would show
it. All fourteen load without error.

Dynamic references were checked by parsing the whole package and collecting
every attribute name reached through a runtime lookup, then cross-referencing
each against every definition in the tree. Of the names with no definition
anywhere, all are legitimate: platform-conditional process-creation and
file-open flags probed precisely because they do not exist on every platform,
and attributes belonging to third-party telemetry, command-line, and model
libraries. Not one is an internal symbol the merge dropped. The restored
provider method would have appeared in that list had it still been missing,
which is what makes the sweep's negative result meaningful rather than merely
empty.

The statically-visible set is not this audit's concern and is being repaired
separately; one had already landed when this ran.

Recorded as a clean result deliberately. A verified negative on a class that
static gates cannot see is worth as much as a hit, and without it the honest
position would have been that the merge's blast radius was unknown rather than
bounded. The method is reusable and is the point: load the presets, and
cross-reference dynamic lookups against definitions.

- `researcher-persona-advertises-an-undeclared-server` (high, open) - the
  researcher persona instructs the agent, by exact tool name and five times over,
  to query and fetch through a web-search MCP server that no shipped preset
  declares. Only two presets declare harness servers at all and both declare the
  semantic-search server alone, so the advertised tools cannot be present in any
  run. The agent is told to reach for something the harness never mounts.

  This is the capability-claim-without-proof defect the project's own served-
  profile rule exists to prevent, one layer in: the rule governs what a preset
  may advertise about a provider lane, and the same standard plainly applies to
  what a persona advertises about its tools. A persona is a claim about what the
  agent can do, and an unbacked claim degrades the run silently - the model
  attempts a tool call that cannot resolve, and recovers by improvising rather
  than by reporting that its grounding is absent.

  The registry entry itself is sound and is NOT the defect: it is keyless,
  declares both trust axes correctly including the network reach that makes it
  the registry's one egressing member, and sitting undeclared in a closed
  registry is a legitimate resting state. The defect is the persona text, which
  crossed from the branch that added the entry without the preset declaration
  that would have made it true.

  Recorded here rather than fixed in place because the persona is the delivery
  Step's own surface: that Step composes web-capability text lane-conditionally
  behind the proven-lanes gate, and the correct repair is to replace an
  unconditional claim with a gated one rather than to delete a line.

### The Claude lane live proof is blocked on infrastructure, not on code (2026-08-01)

The Claude web-grounding proof is written, committed, and skips truthfully. Its
Step cannot close, and the reason is worth recording precisely so the next
attempt does not re-derive it.

The suite reuses the standing acceptance harness rather than adding a second
driver, and its reachability gate wants three things together: a resolvable
engine, a gateway answering health, and a service record whose path locates the
workspace vault. Each was probed directly.

The gateway is not listening. Nothing answers on the port the harness defaults
to, and this repository's development compose stack cannot supply one that
satisfies the gate on its own, because that stack contains only the gateway and
the worker - there is no engine service in it at all. The engine is the
consuming project's binary and lives in a different repository.

An engine IS running, from a debug build in that other project's worktree, and
it is serving. But the gate does not resolve an engine by port; it resolves one
through a service record, and derives the workspace vault from that record's own
path. The machine-global record cannot serve: its path does not sit under a
workspace vault, so the derivation yields a directory that is not one. The only
record with the right shape belongs to another worktree, is fourteen minutes
stale, and names a process that is no longer alive - and a stale record is
refused by design rather than tolerated, which is correct and is the mechanism
working.

So the missing piece is specific: a freshly served workspace-local engine whose
record lands under that workspace's vault, plus this branch's gateway and worker
pointed at it. Not a code change, and not something this plan can close from
inside one repository.

Two things follow. The Step should stay open rather than be closed on partial
evidence, because its acceptance is a real retrieval landing in checkpointed
state AND disclosed in a proposed document body, and neither half is reachable
without the stack. And the bounds Step that depends on this lane being proven is
blocked behind it for the same reason, as is the third-lane proof.

The Codex lane is unaffected and is proven: it needs no engine, because its
retrieval happens inside the provider's own turn rather than through the
authoring path.

### Why the live lane proofs never succeed: the harness cannot find or authenticate to a gateway the registry knows (2026-08-01)

Chasing one skipping proof to ground produced a finding larger than the Step.
The lane test has never passed on this host, and the reason is not the lane.

**Ports are controlled, and the control is deliberate.** Development processes
take a port allocated from their role's band and register it machine-globally
with their pid, role, workspace, and liveness. Nothing is guessed and nothing is
fixed: the registry is the discovery mechanism, and a second concurrent session
gets a different port by design rather than colliding. That is a good design and
it works - probing the registry located a live engine, gateway, and worker in
seconds after the defaults had said nothing was there.

**The live-test harness does not consult that registry.** It reads a gateway URL
from an environment variable and falls back to a fixed default. On this host the
gateway had been allocated two ports away from that default, so the harness
concluded no stack existed and skipped truthfully - while the registry knew
exactly where it was. Two mechanisms this project owns, neither wired to the
other. The skip was honest and the conclusion it reported was wrong.

**The service token is deliberately not discoverable, and that half is correct.**
The gateway validates a service token that the configuration explicitly refuses
to share with worker IPC or embed in discovery, and a validator rejects any
configuration collapsing the two authorities. The registry record carries the
internal IPC token file and no service token, exactly as intended. So a harness
CAN learn where the gateway is and CANNOT learn how to authenticate to it -
whoever starts the stack must hand that credential over out of band. Supplying
the internal token instead produces a 401, which is the separation working.

The consequence is a class rather than an incident: any live test gated on a
reachable stack will skip on a correctly-running system whenever the port was
allocated rather than defaulted, and will 401 whenever the credential was not
passed out of band. Both failures read as environment problems and neither is.
A proof that cannot run is indistinguishable from a proof that does not hold,
which is why a lane admitted on such a proof cannot be trusted without the
passing line.

The repair is not to relax the gate. It is to let the harness resolve the
gateway the same way everything else does - through the registry that already
records it - and to make the out-of-band credential an explicit, named
prerequisite rather than an environment variable a caller is assumed to know.

### stale-service-record-outlives-its-engine | high | open

A service record can outlive the process it describes and keep answering, so
discovery refuses a stack that looks alive by every casual check. This sits
BENEATH the registry finding above: that one explained why a harness looks in
the wrong place, this one explains why looking in the right place still fails.

Measured directly rather than inferred. The record at `~/.vaultspec/service.json`
named port 18767 and pid 56188. Three facts held at once: `GET /health` on that
port returned 200; `last_heartbeat` advanced by exactly 0 ms across 8 s of wall
clock; and pid 56188 did not exist. A live server, a frozen heartbeat, and a dead
owner - the port had been inherited by an unrelated engine while the record went
on describing a corpse.

`resolve_engine` is right to refuse this, and does: it requires a fresh heartbeat
before it will trust a record, so an 8.4 h age disqualified it. The refusal is
correct and its report is misleading. `_reachable_stack` returns `None`, the
prerequisite rule skips naming an absent engine, and the operator reads "no stack"
while a healthy engine serves two ports away. Liveness was asserted by three
independent signals that disagreed, and the only one discovery consults was the
one that had silently stopped.

The population makes it a class, not an incident. Sweeping every engine record on
the host: exactly ONE was live (`_s08ws`, port 18767, pid 93632, heartbeat ~9 s).
Every other record named a dead pid with a heartbeat frozen ~8.5 h earlier,
including the engine that the one REGISTERED gateway is paired to - that gateway
is orphaned from an engine that no longer exists, while the healthy gateway
serving alongside it appears in no registry record at all. Two gateways, and
the registry describes the broken one.

Consequences worth separating, because they have different fixes:

- **A frozen heartbeat is indistinguishable from a slow one.** The writer stops
  while the server continues, so the failure is silent on the serving side. This
  is the same shape as the Windows directory-lease defect already fixed in
  `desktop/_filesystem_authority.py`, where a transient sharing violation
  permanently killed a heartbeat writer that nothing restarted. Fixing the lease
  removed one cause; nothing yet detects the effect.
- **A stale record is never reaped.** It persists at the well-known path,
  shadowing any healthy engine, because `_candidates` prefers it and nothing
  invalidates it when its pid dies. A liveness check that consulted the pid
  would have rejected it instantly and for free.
- **The skip reason names the wrong prerequisite.** "engine unavailable" was
  false; the engine was available and its record was stale. An operator who
  trusts that message boots a second engine and makes the contention worse.

Verified reachable once the env var was pointed at the live record: the proof
resolved the stack, minted per-role tokens, and reached run-start before failing
on the separately-tracked service-token gap above. So the two findings compose -
this one hid the other, and neither is a defect in the test.

Recommend the record carry, and discovery check, an owner-pid liveness test
alongside the heartbeat, since a dead pid is a cheap, unambiguous disproof that
does not depend on a writer still running. Recommend a stale record be reaped or
refused at the well-known path rather than left to shadow a healthy peer. Both
are cheaper than the standing cost, which is that no live proof on this host can
be trusted to have run at all.

### live-stack-wiring-is-functional-and-was-never-the-defect | resolved

The harness, gateway, worker, graph, ACP transport, and provider CLI form a chain
that WORKS end to end. This is asserted from a run, not from reading.

A gateway was booted on an explicitly chosen free port against the one live
engine, with a distinct internal token and gateway service token. It reached
`ok`, auto-spawned its worker, and the worker reported ready in 11.6 s. The
subscriber immediately transacted with the engine - `/authoring/v1/events`,
`/authoring/v1/recovery`, and `/health` all answering 200. The proof then ran for
18 s, resolved the stack, minted per-role tokens, started a run, drove the graph
into the researcher's ACP session, and reached Anthropic - which refused with
`ACP Error [-32603] ... errorKind: rate_limit`, naming a weekly window that
resets 2026-08-04.

Every link in the chain is therefore proven live except the model's reply. The
long-standing reading that this wiring was broken or dead was WRONG: the wiring
was fine and the discovery layer was pointing at a corpse, per the finding above.

Two operational notes worth keeping. The worker spawns LAZILY on first dispatch,
not at gateway boot, so a health check taken before then truthfully reports
`worker_connected: false` and must not be read as a failed boot - wait for it. And
the verdict subscriber emitted 264 `/authoring/v1/recovery` calls while idle,
logging `cursor_ahead_of_high_water (latest_outbox_seq=0)` each time: a busy
retry loop against a healthy engine whose outbox is simply empty. It is not
fatal and did not affect the run, but it is unbounded polling on an idle system
and is queued here rather than lost.

### claude-web-lane-admitted-on-a-proof-that-cannot-yet-run | high | open

`PROVEN_WEB_LANES` admits the claude lane citing
`test_claude_web_grounding_live.py::test_claude_lane_completes_a_real_web_retrieval`.
With the infrastructure now proven (above), that test has been driven as far as
the provider and STILL has never returned a pass: the account's weekly window is
spent until 2026-08-04. The skip is truthful and correctly refuses to mask the
gap, so the lane's `tool_names=("WebFetch",)` activation rests on no passing run.

This is a live violation of the project's own admission rule, which requires a
completed real turn - not a handshake, not a construction, not an infrastructure
proof - before a lane may be named where profiles are served. The infrastructure
finding above does NOT discharge it: reaching the provider proves the transport,
not the retrieval.

Deliberately not withdrawn unilaterally. Withdrawal leaves three composition
tests with no proven-web subject and would be reversed within days, so the
choice between withdrawing now and re-running on 2026-08-04 belongs to the
owner. What must not happen is the gap being forgotten because the wiring
finally works - a proof that cannot run and a proof that fails are the same
evidence, which is precisely why this entry stays open.

### acp-identity-fix-review-gate (2026-08-02) - REVISION REQUIRED

Independent review of `27dc0dac` (the ACP identity fix that deleted
`providers/_acp_config_home.py`) by the dedicated review persona. Verdict:
FAIL on the ACP isolation lane. The identity diagnosis was right; what was
removed on the way is the problem. Findings below spot-verified by the
dispatching lead rather than accepted on report.

- `acp-account-connector-suppression-has-no-replacement` (**critical**, open) -
  the harness-provisioning ADR records that the config-home redirect closed TWO
  scopes: the operator's user-global `mcpServers` AND the account's remote
  connectors. The replacement, `project_confinement_settings`, builds its deny
  set from `enumerate_ancestor_mcp_names() | ambient_user_mcp_names()`, and
  `ambient_user_mcp_names` (`providers/_acp_project_mcp.py:362`) reads ONLY
  `$CLAUDE_CONFIG_DIR/.claude.json` or `~/.claude.json` - VERIFIED by reading the
  function. Account-side OAuth remote connectors are not in that file; they live
  server-side on the account. The old mechanism suppressed them STRUCTURALLY, by
  running in a home holding no credential. The child now runs under the
  operator's real login with full OAuth, so those connectors load and are
  neither disabled nor tool-denied. This is the S10 write-leak class - a live
  Claude run scaffolding into `.vault/` through a user-global writable MCP -
  reopened on the lane where it was first observed, with no test covering it
  because the four deleted isolation tests were its only coverage.

  The causation is worth stating plainly for whoever picks this up: the removal
  was CORRECT and is not to be reverted. Suppression-by-credential-absence was
  precisely what broke subscription identity, and the owner's contract is
  explicit - we implement no authentication, the provider inherits the ambient
  environment, the installed ACP binary runs as the operator does. So the fix
  cannot be "put the isolated home back". Either an enforceable ambient-connector
  control is built that does not touch identity, or the ADR is amended to state
  which scopes are now out of scope and why the write-leak class is acceptable
  there. What is not acceptable is the current state, where the record describes
  a mechanism that no longer exists.

- `acp-isolation-fail-loud-gate-is-orphaned` (high, open) - the ADR names two
  fail-loud gates backing the pin. The spawn-time raise was removed with the
  module; `IsolationRequiredError` survives at `thread/errors.py:188`, is
  exported, and its docstring still describes the compile gate. VERIFIED: **zero**
  raise sites tree-wide, sole importer an existence assertion in
  `thread/tests/test_errors.py:524`. Orphaned capability plus a tautological
  test - the same shape as `mark_permission_response_applied`. Reinstate a gate
  or delete the class and its test; carrying a raise-less error class that an
  ADR clause names as binding is the worst of both.

- `acp-unarmed-runs-surface-the-whole-ambient-configuration` (high, open) -
  confinement is applied only when a run declares servers, so an unarmed run
  surfaces the operator's entire MCP configuration, including any writable vault
  server. May be the right product call; landed without amending the record.

- `acp-api-key-scrub-removed-silently` (medium, open) - the
  `ANTHROPIC_API_KEY` pop under `CLAUDE_CODE_OAUTH_TOKEN` was removed. Consistent
  with the no-auth contract, but on a box carrying a key this means silent
  metered billing instead of the subscription, and no record acknowledges it.
  `providers/tests/test_acp_migration_surface.py:22` still asserts in prose that
  the key is scrubbed from every agent subprocess while popping it locally, so it
  exercises production behaviour in neither direction.

- `acp-confinement-residue-lands-in-the-operator-workspace` (medium, open) -
  the replacement writes `<run_workspace>/.claude/settings.local.json` and relies
  on a `finally` to restore it. Tree-kill reaps are routine here, and the old
  design's residue sat in an accounted temp root with a stale-age sweep; this one
  sits in the operator's own source tree with no sweep, so a killed run can leave
  our confinement governing the operator's interactive `claude` indefinitely.

- `acp-confinement-control-is-weaker-than-claimed-and-unproven-live` (medium,
  open) - the docstring claims every other known server is "disabled by name AND
  tool-denied". `enabledMcpjsonServers`/`disabledMcpjsonServers` govern
  PROJECT-scope `.mcp.json` servers, so for a user-global name only the
  `permissions.deny` half applies: the server still registers and its tools still
  enumerate, only invocation is refused. The mechanism it replaced carried
  ADR-recorded live verification on adapter 0.59.0 / SDK 0.3.207; this one has
  none.

Two framework-lane findings were also verified by the lead and belong to the
resource-aware-test-execution audit rather than here, but are cross-referenced
because both defeat safety that this lane's live proofs depend on: the pytest
plugin is dropped by `dev/toolchain.py`'s `ADDOPTS_OVERRIDE` on the service
target (VERIFIED: `pyproject.toml` addopts carries `-p`, the override does not),
so the service tier runs with the whole framework disabled; and reservation
markers have no heartbeat refresher (VERIFIED: zero `utime` calls in
`lifecycle/registry.py` against one plus a refresher thread in
`testing/leases.py`), so every held port decays at the 300s TTL inside a
40-minute suite.

### desktop-admission-refuses-three-commit-heavy-runs | medium | open

Three `desktop_tests/test_run_admission.py` cases refuse with `run admission is
not execution-ready` where they expect a 201:
`test_concurrent_prepare_bounds_capacity_and_commit_is_reservation_bound`,
`test_exact_commit_replay_role_binding_release_and_race_are_linearized`, and
`test_pre_durability_commit_failure_restores_reservation_for_release`.

NOT the explicit-selection migration. Both stages now carry a properly derived
selection and four siblings in the same file pass on the same helpers; these
three were failing before that work and still fail after it.

Narrowed, not guessed. `AdmissionBroker.prepare` refuses unless ALL THREE of
`worker_state == ready`, `provider_eligibility == eligible`, and
`run_admission == ready` hold (`control/admission.py:228-241`). Provider
eligibility is NOT the cause: `_eligible_provider_names()` returns
`['claude', 'codex', 'kimi']` on this host, so that leg is satisfied. The
refusal therefore comes from worker state or the composed admission verdict,
both of which turn on a reachable worker.

Two facts sharpen it. The sibling that EXPECTS this refusal
(`test_prepare_refuses_when_real_worker_is_not_execution_ready`) passes, so the
refusal path itself works. And the three failures are exactly the commit-heavy
cases - concurrent prepares, a replayed commit, and a post-authorization
conflict - while the prepare-only and timeout cases pass. That points at worker
reachability under repeated or concurrent demand rather than at first-demand
startup.

Hypotheses tried and rejected: catalog cold-probe latency shifting the timing
(warming the catalog at arm time changed nothing), and a per-workspace catalog
difference (two of the three anchor on cwd, one on a temp workspace).

What would settle it is the readiness payload itself. `PrepareOutcome` carries
the probed `AdmissionReadiness`, but the HTTP refusal discloses only the reason
string, so the failing leg is invisible to the test. Surfacing the three facts
on the 503 - or logging them at refusal - would turn this from an inference into
a reading, and is worth doing regardless of this defect.

### commit-refusal-order-contradicts-the-bogus-reservation-expectation | medium | WITHDRAWN

With the cold-start race closed, the three desktop admission failures moved to a
single remaining subject: a commit naming a reservation that does not exist
answers 503 where the test expects 409.

The cause is an ordering the ADR mandates rather than a defect in either side.
`_run_commit_locked` evaluates execution eligibility and returns 503 at
`api/routes/gateway.py:760`, BEFORE `broker.commit(...)` at :767 - the call that
would recognise an unknown reservation and answer 409. The comment above it
states the constraint directly: "Evaluate worker and provider eligibility BEFORE
consuming the reservation, accepting the actor tokens, or creating a run (ADR:
mint run credentials only after the runtime and provider are eligible)."

So whenever eligibility is unsatisfied, every commit refusal is 503 regardless
of whether its reservation was real. The test asserts the opposite: that a bogus
reservation "is refused the same way" as any other, with 409.

Both positions are defensible and they cannot both hold. An unknown reservation
is arguably not requesting execution capacity at all, so validating it first
would refuse a nonsense request without probing the runtime - cheaper and more
truthful. Against that, the ADR's ordering exists so no credential is minted and
no reservation consumed while the runtime is not eligible, and reordering would
put reservation lookup ahead of the gate that clause protects.

Deliberately not resolved here. Changing the order is a production change to the
admission sequence on a constraint an accepted ADR states in the code itself,
and this session already shipped one change that contradicted an ADR after
verifying it against behaviour instead of against the record. The decision is
whether the ADR's "eligibility first" applies to requests that reference no
capacity, and it belongs in an amendment rather than in a reordering.

**WITHDRAWN (same session, before anyone acted on it).** The reasoning above is
wrong and is kept only so the error is legible.

It asserted that the 503 comes from the eligibility gate at
`api/routes/gateway.py:760` firing ahead of the reservation check at `:767`, and
concluded that an ADR-mandated ordering conflicted with the test. Instrumenting
that gate disproved it: the commit refusal logs NOTHING there, so eligibility is
satisfied and that branch is never taken. Worker state and provider eligibility
both report ready once the cold-start race is closed.

The 503 therefore originates earlier in `_run_commit_locked`, before
`broker.commit` is ever reached. The remaining candidate is
`_validate_and_freeze_selection_or_refuse` (`:740`), which answers 503 on
`ProviderCatalogScopeCapacityError` - a bounded per-workspace scope count in the
catalog service - and these suites start many gateways. That is a hypothesis,
not a finding; it has not been observed.

The lesson is the one this audit already records twice against other work:
severity and cause were inferred from a plausible reading of nearby code rather
than from an observation, and the reading was confident enough to be committed.
The disclosure that disproved it took three lines. Instrument first, conclude
second.

### desktop-commit-503-remains-unlocated | medium | open

The bogus-reservation commit in
`test_concurrent_prepare_bounds_capacity_and_commit_is_reservation_bound`
answers 503 where 409 is expected. Three candidate sources have now been
ELIMINATED BY INSTRUMENTATION rather than by reading:

1. The execution-eligibility gate (`api/routes/gateway.py:760`). Instrumented;
   never fires. Worker state and provider eligibility both report ready once the
   cold-start race is closed. This was the subject of the withdrawn finding
   above.
2. The provider-catalog workspace scope bound in
   `_validate_and_freeze_selection_or_refuse`. Instrumented; never fires.
3. The commit wrapper `_run_commit`. Read; it raises only 422.

So the refusal is raised somewhere between entering `_run_commit_locked` and
reaching `broker.commit`, and it is none of the three places that looked most
likely. `broker.commit` itself is the call that would answer 409 for an unknown
reservation, and it is not being reached.

Left open deliberately rather than guessed at a fourth time. The next step is
mechanical and cheap: the two refusal disclosures added today already log which
fact refused a prepare and an ineligible commit, so extending the same treatment
to the remaining raise sites in that window will name this one in a single run.
Every hypothesis formed by reading this path has been wrong; the instrument has
been right twice.

**Narrowed further, same session.** Exhaustive read of every raise reachable
between entering `_run_commit_locked` and `broker.commit`: `_prepare_workspace_root`
raises nothing, `_load_preset_or_refuse` raises only 422 twice, and
`_validate_and_freeze_selection_or_refuse` raises 422 three times and 503 exactly
once - the catalog scope bound already disproven by instrumentation. The
eligibility gate is disproven. So NO 503 source exists in that window.

The refusal therefore cannot precede `broker.commit`; it must follow it. That
inverts where the defect lives: `broker.commit` is not refusing an unknown
reservation, execution continues into `_create_run_core`, and the 503 comes from
the drain/admission gate at `:456` - whose reason string,
"run-admission reservation capacity is exhausted", is exactly what the gateway
log shows.

If that holds, the defect is not an ordering question at all: a commit naming a
reservation that never existed is being treated as admissible, and only the
concurrency bound stops it. The test's expectation of 409 is then correct and
the broker is wrong, which is the opposite of what the withdrawn finding above
concluded.

Still stated as an inference, because the one thing not yet observed is
`broker.commit`'s own outcome for a bogus id. Logging that outcome answers it
outright, and is the single remaining step.

**LOCATED - WITHDRAWN (same session).** Instrumenting `broker.commit`'s own verdict settled
it, and disproved the inference immediately above as well. The run logs exactly
ONE verdict - `committed=True` for the real reservation - and none for the bogus
one. So `broker.commit` is NOT wrongly admitting an unknown reservation; it is
never reached.

The refusal therefore precedes stage dispatch entirely. It is raised in the
shared part of `run_start_endpoint`, before the commit stage is selected, which
is why an exhaustive read of the commit path found no 503 to blame: the gate was
never in that path. The reason string the gateway logs - "run-admission
reservation capacity is exhausted" - belongs to the run-admission bound applied
to every stage alike.

That makes the defect a scoping question rather than an ordering or broker one:
a commit references capacity that was already reserved, so applying the
new-run admission bound to it double-counts, and the second reservation in a
capacity-two test makes any subsequent commit look like a third run. The test's
409 expectation stands; the bound is being applied to a stage that is not
requesting new capacity.

Three inferences were drawn from reading this path today and all three were
wrong - eligibility ordering, catalog scope capacity, and a permissive broker.
Each was corrected by one instrument, and the instruments cost three lines each.
The disclosures are retained in the code for that reason.

**The "located" claim above is WITHDRAWN too.** It asserted the refusal comes
from a gate in the shared part of `run_start_endpoint` before the stage is
selected. There is no such gate: stage dispatch sits at lines 320-327 with
nothing preceding it. The gate's existence was inferred from the ABSENCE of a
broker verdict and then written up as a location.

So the standing facts are only these, each observed:

- The eligibility gate never fires (instrumented).
- The catalog workspace-scope bound never fires (instrumented).
- `broker.commit` is never reached for the bogus reservation (instrumented).
- No 503 is raised anywhere between entering `_run_commit_locked` and
  `broker.commit`, and nothing gates the stage dispatch above it (read).

Those cannot all be true of the code as read, which means the reading is wrong
somewhere rather than the observations being wrong. The unexamined candidate is
`_run_commit` itself (`:659`) - the per-run stripe lock it takes before
delegating to `_run_commit_locked` - which was checked for `raise` statements
but not for what it does when a lock cannot be acquired.

Four inferences about this path today, four wrong, every one corrected by an
instrument. The next person should not read further code: instrument
`_run_commit`'s entry and exit and let the run say it.

**Observed boundary (no inference).** Instrumenting `_run_commit`'s entry
alongside the broker verdict gives the tightest true statement available:

    commit entered: run_id=run-capacity-1        reservation=resv-457e3ff4...
    commit entered: run_id=run-capacity-1        reservation=resv-457e3ff4...
    commit entered: run_id=run-bogus-reservation reservation=resv-deadbeef...
    commit broker verdict: reservation=resv-457e3ff4... committed=True

The bogus commit ENTERS `_run_commit` and never produces a broker verdict. So
the 503 is raised strictly between commit entry and `broker.commit`. Both 503
sources known to exist in that window are instrumented and provably silent for
this request, and the remaining calls there raise only 422.

That is a contradiction between four observations and the code as read, and it
is where this hands over. The observations are trustworthy - each came from a
run - so the reading is what is wrong. The cheapest next move is to instrument
the window exhaustively rather than narrow it further by argument: log at each
call boundary inside `_run_commit_locked` and let one run name the line.

Everything above this point that named a cause was withdrawn. This entry names
no cause deliberately.

**LOCATED, from the trace (2026-08-04).** Boundary tracing named the line in one
run. The bogus commit's sequence ends at `probe_worker`:

    commit entered: run_id=run-bogus-reservation
    commit step: probe_worker            <- last record for this request

No eligibility-refusal record, no broker verdict. So the 503 is raised INSIDE
`_admission_readiness(...)` or `evaluate_execution_eligibility(...)` and never
returns to the `if not execution.eligible` gate at `:760` - which is exactly why
instrumenting that gate showed nothing, and why four readings of the surrounding
code were wrong. The refusal is not at the branch that looks like the refusal.

The remaining step is a single read of those two helpers for a raise, now that
the trace says which two lines to open. Every earlier attempt read the whole path
and inferred; this one narrowed by observation to two calls.

Method note worth keeping beyond this defect: five diagnoses were attempted here,
four by reading and one by tracing. The four were wrong and each cost a
withdrawal; the trace was right first time and cost four log lines. Where a
refusal is silent, instrument before reasoning.

**Correction to the location, from reading the two named helpers.** Neither
raises: `evaluate_execution_eligibility` (`control/run_start_policy.py`) contains
no raise at all, and `_admission_readiness` only projects seated facts. So the
503 does not originate in either.

The trace still bounds it exactly, and one call earlier than the previous entry
said. `commit step: probe_worker` is logged BEFORE `probe_worker_health(...)`,
and nothing is logged after it, so the request does not survive that call. The
remaining candidate is `probe_worker_health` itself, or the awaiting of it -
the one thing in the window that performs I/O against another process.

That fits the shape of the failure better than any of the five earlier
candidates: it is the only step whose behaviour depends on a live peer rather
than on local state, which is why it fails for the commit-heavy cases and not for
the prepare-only ones, and why every attempt to find it by reading control flow
missed it.

Left here with the boundary observed and the candidate named rather than
asserted. The trace lines are committed, so re-running the test reproduces this
in 40 seconds.

**RESOLVED (2026-08-04). The eligibility gate WAS the cause; every "it is not"
above was a reading error of my own logs.**

The refusal record exists. `run commit refused as ineligible` appears exactly
once in the gateway log for this test. Each earlier check that reported it
absent was grepping a DIFFERENT pytest temp directory - the suite creates a new
one per run and I repeatedly read a stale one - so "the gate never fires" was
never an observation at all. It was a failed lookup reported as a negative
result, which is worse than an inference, and it invalidated three subsequent
entries built on it.

The actual chain, all observed in one log:

    commit entered: run_id=run-bogus-reservation
    commit step: probe_worker
    run commit refused as ineligible

`probe_worker_health` returns `healthy=False` (it raises nothing - it reports),
so `evaluate_execution_eligibility` is not satisfied, the gate at
`api/routes/gateway.py:760` answers 503, and `broker.commit` is never reached -
which is why no broker verdict was logged and why an unknown reservation never
gets its 409.

So the ORIGINAL finding was right: eligibility is evaluated before the
reservation is consulted, and while the worker is unreachable every commit
refusal is 503 regardless of whether its reservation existed. Whether the
ADR's "eligibility first" should apply to a stage that consumes no new capacity
remains the open decision, exactly as first recorded.

The lesson is not "instrument before reasoning" - the instruments were right
throughout. It is that a grep returning nothing is not evidence of absence until
you have proven you searched the right file. Five withdrawals here trace to one
unverified lookup.

**Complete, with the refusal's own words (2026-08-04):**

    run commit refused as ineligible: reason=the gateway worker is not
    execution-ready worker_reachable=False provider_eligibility=eligible
    reservation=resv-deadbeef...

So the 503 is TRUTHFUL. At the moment of the bogus commit the worker is
genuinely unreachable, the provider side is fine, and the gateway refuses for
the reason it states. Nothing is misreporting anything.

That reframes the defect one last time, and away from the ADR question. The
test's 409 is unreachable not because eligibility is ordered ahead of the
reservation check, but because the WORKER HAS GONE UNREACHABLE partway through a
test that earlier committed a run successfully. The same subject as the
cold-start race fixed earlier today - worker reachability under repeated demand -
seen from the other end: there the worker was up and reported cold, here it
reports unreachable after serving a commit.

Two candidates, both cheap to separate with the disclosures already in place:
the worker is reaped or dies after the first commit, or the probe targets a
worker URL that stops resolving once the first run settles. Either is a genuine
defect in the desktop lane rather than a test expectation problem.

The ADR ordering question raised at the top of this thread remains open on its
own merits, but it is NOT what these three tests are failing on.


## Closed (2026-08-04): the worker was never gone, only busy

Both candidates above were wrong, and the disclosure that settled it was the one
missing all along: `probe_worker_health` swallowed every transport exception
without naming it. With the exception typed, the failing probe reports
`ReadTimeout`, not `ConnectError` - the connection was established and accepted,
the worker simply did not answer inside the two-second budget.

An unauthenticated probe fired from the TEST process, on its own fresh client,
times out at the same instant and answers normally one second later. That rules
out the gateway's pooled client and rules out the worker dying: the worker is
alive, listening, and unresponsive for a window.

The window is the first ingest. The worker logs `dispatch_accepted` and then
nothing for 7.4 seconds, until `Instantiating ProviderFactory`. Resolving a
provider and compiling the graph makes the whole process unresponsive for that
long, and any admission request arriving inside it was refused as if no worker
existed.

The fix is at the reading, not the timing. A refused connection OBSERVES absence;
a read that outran its budget observes nothing. `WorkerHealthProbe` now carries
that distinction, and admission acts on absence only where absence was observed -
an indeterminate probe defers to the worker's own heartbeat. Landed in
`dc7c9272` with a real accept-and-never-answer server pinning the classification.

### Findings raised by this investigation

- **HIGH - `control/event_handlers.py:74`.** When no session factory is injected,
  the terminal-event handler substitutes the ambient application factory. An app
  that seats no database therefore performs a durable write against whatever the
  process default resolves to, rather than skipping the write it has no store
  for. Observed as `sqlite3.OperationalError: no such table: threads` failing
  `api/tests/test_internal.py::TestInternalEvents::test_batch_with_aggregator_only_returns_ok`,
  which is a truthful test of an app with a relay target and no database. Same
  ambient-default class as the production-boundary campaign. NOT the
  `workspace_root` migration, and not owned by the lane currently editing that
  file.
- **MEDIUM - worker first-ingest stall.** 7.4 seconds of provider resolution and
  graph compilation leave the worker's whole process unresponsive. The admission
  fix makes it non-fatal, not absent: `/health`, the watchdog, and any second
  dispatch all wait on it. The compile path is documented as synchronous work
  inside an `async def`, so the work is on the loop by construction.
- **MEDIUM - `utils/logging.py:178`.** The JSON formatter indexes
  `record.exc_info` unconditionally and raises `TypeError: 'bool' object is not
  subscriptable` when a record carries `exc_info=True`, which the OTel exporter
  produces. Every such record is lost to a logging error. File is held
  uncommitted by another lane; not edited here.
- **LOW - telemetry default in tests.** Workers boot with an OTLP endpoint of
  `198.51.100.1:4317`, a blackhole address, so gRPC export retries with ten-second
  deadlines and floods worker stderr through the whole run.
- **LOW - flaky under back-to-back gateway boots.**
  `desktop_tests/test_lazy_worker.py` and four `api/tests/test_thread_metadata.py`
  cases each failed once and passed on isolation and on re-run - the metadata ones
  on a Windows temp-directory pin, `os.rmdir` refused on an already-empty
  directory. Not reproduced deterministically.

## Closed (2026-08-04): run start no longer absorbs a cold catalog build

Measured, not estimated: a cold `records()` for one workspace took over a minute
on this host, with several ACP lanes timing out inside it. Run start awaited that
with no bound, so a caller could not distinguish a building catalog from a hung
gateway.

Reachable in production rather than hypothetical - a gateway restart, or the
workspace scope evicted under its bounded capacity, between the client's catalog
read and the start that revalidates against it.

Bounded in `194627d2`. The build is shielded rather than cancelled, which is the
load-bearing half: cancelling would make every retry pay the same cold cost and
never converge. The refusal is a genuine "not yet".

## Decided (2026-08-04): where the opinionated default lives

The open question was whether A2A's own default should be surfaced as a model
NAME or as a low/medium/high tier. The accepted catalog record answers it: no
centrally maintained model-tier mapping may exist in production source, and a
tier is exactly that mapping. So: by name.

Effort is a separate axis that already belongs to the provider - each lane's
native controls carry the provider's own default option - and is not A2A's to
decide.

The default itself is a RULE over what a lane advertises, never a list of names:
capability vocabulary first, the provider's own enumeration order otherwise. A
lane that starts advertising a new model gets a recommendation for it with no
repository release, which is the whole difference from the static map this
replaces. Served as `recommended_entry_id` beside the catalog rather than inside
it, because the opinion is A2A's and not the lane's. Landed in `7a4ac75b`.

This unblocks the persona-policy cleanup: with a served recommendation, presets
have no remaining reason to carry provider or capability policy.

### Correction (2026-08-04): the first catalog budget was below the real worst case

The bound shipped at eight seconds and refused legitimate work. Each desktop test
boots its own gateway, so each starts cold, and running them back to back loads
the host enough that a build the suite would have completed is refused instead.

Raised to 120 seconds, above the ~74s cold build measured here. The bound still
does its job - it converts an unbounded wait into a bounded, retryable one - but
it now bounds a HUNG build rather than a slow one.

- **MEDIUM - failed lane discovery is not cached.** A lane whose discovery raises
  leaves nothing in the per-lane cache, so every later read retries it at full
  cost. That is why a second read after a warm one is not fast on a host where
  several ACP lanes time out, and it is what made a small budget look reasonable
  and behave badly. A negative cache entry with its own short expiry would make
  the warm path actually warm.

## Partially closed (2026-08-04): the ambient database on the durable event path

The HIGH finding above is fixed at its worst edge and blocked at its last one.

Fixed in `e52069a6`: the relay handlers no longer MANUFACTURE a database. They
ask for the application factory instead of `get_session_factory()`, which creates
an engine from ambient settings when none was initialized, and they skip the
durable write loudly when there is none.

That fix uncovered a regression it would otherwise have shipped. `init_db` passed
an explicit engine, and `get_session_factory` deliberately leaves the singleton
alone for an explicit engine, so a fully booted gateway reported NO database - and
the new skip would have dropped every durable projection in silence. Strictly
worse than the defect. `init_db` now seats the singleton, with both halves pinned:
initialising seats the process factory, an explicit engine still does not adopt
the process.

**Still open, and blocked on a contended file.**
`api/tests/test_internal.py::TestInternalEvents::test_batch_with_aggregator_only_returns_ok`
passes in isolation (44/44) and fails in a full `api/tests` session. The cause is
not the handler any more, it is the question the handler is forced to answer:
"this app declared no database" and "this app did not inject one, use the
process's" arrive identically as `session_factory=None`. In a full session an
unrelated test has already seated the process singleton, so the bare app finds a
database it never had.

Closing it needs the gateway to seat `app.state.db_session_factory` at boot,
making an app's database an app-level fact, after which the ambient consult can
be removed entirely. That edit is in `api/app.py`, which is held uncommitted by
another lane and was not touched.

The `workspace_root` migration in the same file remains that lane's: its
`_WORKSPACE` edits are uncommitted and passing.
