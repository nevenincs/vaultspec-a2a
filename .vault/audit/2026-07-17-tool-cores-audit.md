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
