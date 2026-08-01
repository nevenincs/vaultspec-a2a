---
tags:
  - '#audit'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:05161b7d92f2e26a6a3479f486ada5ad76dbccfa80a3420fc56ad1d8c50be4d6'
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
