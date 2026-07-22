---
tags:
  - '#adr'
  - '#capsule-install-layout'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-18-desktop-product-profile-plan]]'
  - '[[2026-07-21-capsule-install-layout-reference]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace capsule-install-layout with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, superseded, or deprecated. A new ADR starts as proposed; it
     moves to accepted or rejected when the decision is made; it becomes
     superseded when a later ADR replaces it (set by vault adr supersede,
     which also records superseded_by); and deprecated when it is retired
     without a direct successor.

     Amend vs supersede: refinements and concretization rewrite the accepted
     record's body in place (modified: carries the revision); a new ADR with
     supersession is only for a major pivot. One accepted record per
     decision.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `capsule-install-layout` adr: `one wheel-aware install-layout authority with a provenance-bearing installed inventory` | (**status:** `accepted`)

## Problem Statement

The landed capsule assembly planner trusts the installed closure inventory as
the declared installed tree and reserves every closure destination from it, but
nothing in production builds that inventory: its builder is called only from
test fixtures that declare arbitrary paths, and the file record carries no
per-file byte provenance. The bounded projector deliberately refuses generic
wheel installation and offers only verbatim prefix projection. The materializer
(plan step `W01.P03.S103` of `2026-07-18-desktop-product-profile-plan`) must
therefore write wheel and npm bytes into the capsule with no authority defining
where each byte lands or which source member produced it, and no way to
reconcile the written tree byte-exactly against a declared inventory. The
grounding for these facts and the wheel/npm install semantics lives in
`2026-07-21-capsule-install-layout-reference`. This record decides the
canonical install-layout authority, the production inventory builder, and the
provenance model, within the capsule boundary governed by
`2026-07-18-desktop-product-profile-adr`.

## Considerations

- The governing record requires a relocatable, offline, target-specific capsule
  that runs without system Python, pip, `uv`, or npm across five targets
  (`2026-07-18-desktop-product-profile-adr`).
- Wheel installation is spread-plus-`RECORD` semantics, not prefix projection;
  npm layout is already declared per package; source verification already proves
  `RECORD` completeness and retains member evidence
  (`2026-07-21-capsule-install-layout-reference`).
- Every capsule write must flow through the leased-descriptor filesystem
  authority already used by the projector
  (`2026-07-21-capsule-install-layout-reference`).
- The installed inventory is a content-addressed release input reconciled
  against its descriptor on load, so a format change is a version bump of that
  artifact, not an in-place mutation
  (`2026-07-21-capsule-install-layout-reference`).
- The parallel-implementation hazard is the motivating anti-pattern: if the
  materializer computed layout independently of the inventory builder,
  reconciliation would compare two implementations rather than the tree against
  one declaration.

## Considered options

- **One layout authority feeding a provenance-bearing inventory; the
  materializer consumes only the inventory — chosen.** A pure install-layout
  module maps verified archive members to installed destinations; the production
  builder applies it once at build time and persists the result; the record is
  extended so every file names its source archive and member; the materializer
  replays inventory records byte-for-byte. One definition, two consumers,
  byte-exact reconciliation by construction.
- **Generalize the verbatim projector to wheels.** Rejected: wheel installation
  is spread-plus-`RECORD` semantics; this is exactly the case the projector
  refuses, and weakening the guard would silently install `.data` members at
  wrong paths.
- **Vendor a standard wheel installer at build time and inventory the result.**
  Rejected: such tools target a live interpreter's sysconfig scheme, mutate
  `RECORD`, and expose no per-member provenance, so the materializer would
  replay a tree it cannot derive from records; it also adds a dependency whose
  layout policy this project would still have to constrain.
- **A separate provenance authority beside the unchanged inventory.** Rejected:
  a keyed sidecar splits one fact across two documents, reintroduces join drift,
  and prevents the model validator from atomically cross-checking file, license,
  and provenance identity as the inventory does today.
- **Build-script self-minted descriptor pin.** Rejected: collapsing input
  preparation and consumption into one process makes the digest pin attest only
  that the process hashed what it had just written, inverts the input module's
  stated contract that the workflow supplies a pinned descriptor, and re-grows
  acquisition and derivation logic inside the build script - the
  parallel-implementation defect this record exists to forbid.
- **Bespoke wheel-selection ordering** (compiled over pure-Python,
  architecture-specific over `universal2`, highest satisfied ABI and glibc
  floors). Rejected: the hand rule coincides with the standard tag-priority
  model on the measured lock, but it is a parallel implementation of an
  ordering the pinned `packaging` dependency already defines; every future tag
  family would need a fresh hand decision, and divergence from what the
  ecosystem installer ships on the same baseline would be invisible until
  runtime. The compatibility-tags specification explicitly delegates ranking to
  installers, so adopting the reference installer's model is the strongest
  available grounding.
- **Two separate curated inputs - an expression table and an external-artifact
  table.** Rejected: both entry kinds state facts about one package's license
  identity; splitting them across two documents reintroduces the keyed-sidecar
  join drift this record already rejected for provenance, and prevents the
  validator from cross-checking expression, bytes, and declared member
  atomically per package.
- **Repo-committed per-target descriptors verified by CI.** Rejected: the
  descriptor pins the project wheel built from source head, so its digest (and
  the installed inventories embedding it) changes with every commit; keeping
  five per-target descriptors continuously committed is a regeneration
  treadmill, not an attestation. Cross-run independence is instead recovered by
  publishing the descriptor and its digest as build evidence for downstream
  verification.

## Constraints

- The installed tree obeys the existing dashboard grammar: portable NFC ASCII
  paths, 0644/0755 modes only, sorted unique records, and the 80 000-file and
  8 GiB bounds. No symlinks, junctions, or empty directories are declarable or
  materializable (`2026-07-21-capsule-install-layout-reference`).
- The capsule layout roots are fixed by the landed plan: `runtime/python` and
  `runtime/acp` closure roots beside the verbatim `runtime/cpython` and
  `runtime/node` interpreter subtrees.
- The capsule is a library runtime whose only executable surface is its two
  product launchers; third-party console scripts and build-time headers are not
  part of that surface. A real closure audit of every selected wheel across the
  four targets (`2026-07-21-capsule-install-layout-reference`) found `.data/`
  members in exactly three required packages - `greenlet` (`.data/headers`),
  and `jsonpatch`, `jsonpointer`, `pywin32` (`.data/scripts`) - and no
  `.data/data` or `.data/platinclude` anywhere. Given that finding, `.data/headers`
  and `.data/scripts` members are DROPPED (deterministically omitted, not placed
  and not failed): a frozen offline runtime never compiles against a bundled
  header, and the dropped scripts are third-party CLIs and install helpers
  outside the product surface, while the packages' importable `purelib`/`platlib`
  code still installs in full. `.data/data`, `.data/platinclude`, and any
  unrecognized `.data` key still fail closed with a named build error; nothing is
  best-effort placed. The drop is recorded per member in the build evidence so an
  omission is auditable rather than silent.
- Determinism: identical verified inputs must yield byte-identical inventories
  and capsule trees (canonical JSON, sorted members, normalized modes, epoch
  timestamps).
- Materialization performs no network access and mutates only through the
  leased-descriptor authorities; the generic projector's wheel refusal remains
  in force verbatim — this record adds the non-generic path beside it rather
  than overriding it.
- One sub-decision remains consciously open and must be grounded before the
  dependent step relies on it: the entrypoints 0755 derivation
  (`2026-07-21-capsule-install-layout-reference`). The `.data` closure audit is
  resolved by this revision (drop headers and scripts, fail closed on the rest).
  The Windows `Scripts/{name}.exe` launcher source is resolved by this revision: a
  content-addressed stub input, not a contract change.
- Only the input preparation authority performs network access; the build,
  verify, and publish stages consume the content-addressed cache and the pinned
  descriptor exclusively.
- The descriptor digest is a phase-boundary attestation, not an origin
  attestation: within one release run it proves the build consumed exactly the
  bytes preparation authored and nothing mutated between phases; the
  supply-chain trust root remains the committed, human-reviewed lock and input
  pins the preparation authority verifies against. Cross-run and downstream
  independence come from the descriptor digest published as generation
  evidence, which later verification checks without a source checkout.
- A package resolvable from the lock but lacking a target-compatible wheel, and
  a package lacking both a metadata license expression and a curated override,
  fail preparation closed; curated overrides are committed, reviewed inputs,
  never runtime inference. This holds for both ecosystems: an ACP package whose
  `package.json` license is a non-SPDX `SEE LICENSE IN <file>` reference and has
  no curated override fails preparation closed. Every curated override key -
  wheel or ACP - must resolve to a package that is in the lock at the pinned
  version, checked against the full lock independent of any single target's
  selection, so a stale override for an orphaned package is a validation error
  rather than silently dead data.
- Wheel selection is deterministic and reviewable: the per-target supported-tag
  list is a pure function of the target triple and the fixed compatibility
  baselines (CPython 3.13, glibc 2.28, macOS 13.0); the selection authority
  chooses only among wheels the compatibility predicate admits, and a package
  whose admitted set is empty still fails preparation closed. The closure
  inventory names the selected wheel per package, so a selection change is a
  reviewable inventory diff, never a silent re-pick; the tag-list derivation is
  covered by a fixed vector so a `packaging` upgrade that reorders tags
  surfaces as a visible failure, not a silent content change.
- A curated override is pinned to the exact locked package version: a lock
  upgrade orphans the override and fails preparation closed until a human
  re-reviews and re-pins it, and an override naming a version absent from the
  lock is a validation error, not dead data. Every override carries reviewable
  evidence - the verbatim declaration or pinned locator it interprets - so the
  curation is auditable per entry.

## Implementation

A new pure module (proposed `install_layout.py`) is the single layout
definition. **Wheel layout:** every archive-root member of a verified wheel
maps under one library root, honoring the spread rule for a scheme where
purelib and platlib coincide (true for the bundled per-target CPython, so
`Root-Is-Purelib` true and false wheels land identically); `.data/purelib` and
`.data/platlib` also map there; `.data/headers` and `.data/scripts` members are
deterministically dropped as outside the library-runtime surface (recorded per
member in the build evidence), and `.data/data`, `.data/platinclude`, and any
unrecognized `.data` key are rejected fail-closed; per-file size and sha256 come
from `RECORD`-verified member evidence, not from re-hashing. **npm layout:**
each verified tarball projects verbatim to its declared nested-`node_modules`
destination, with no `.bin` links. **Entrypoints:** the layout derives each
closure's executable entrypoints (ACP root bin script; the Python module files
backing the two contract console-script references), promoted to 0755.
**Product launchers** stay outside the closures as plan-generated files at the
contract-pinned `bin/{name}` and `Scripts/{name}.exe` paths. The Windows
launcher is generated, not vendored whole: a content-addressed console stub -
the x86_64 simple-launcher binary shipped inside the pinned PSF-2.0 distlib
wheel, declared in the input cache by URL, sha256, version, and license like
every other asset - is concatenated at build time with a fixed ASCII shebang
addressing the bundled interpreter relative to the launcher's own directory
(the stub's `<launcher_dir>` token, carrying the same isolated-mode interpreter
flags as the POSIX launcher) and a deterministic epoch-stamped zip whose
`__main__` resolves the capsule root from its own location, pins the
`runtime/python` library root at the head of the import path, and calls the
contract console-script entrypoint. Stub bytes plus fixed shebang plus
canonical zip yield byte-identical launchers from identical inputs; the
packaging library donating the stub is never a build- or run-time dependency.
On Windows the bundled interpreter lives at the interpreter subtree root
(`runtime/cpython/python.exe`; the standalone-build Windows layout has no
`bin/` segment), and the launcher pair is written 0755 like its POSIX
counterpart. **Installed inventory v2:** the
file record gains `source_sha256` and `source_member`, the inventory version
becomes `vaultspec-installed-closure-v2`, and the source-to-installed join
additionally proves every provenance pair names a verified member of a closure
package; the tree-digest preimage is unchanged. **Input preparation authority:** a new production module (proposed
`capsule_input_authoring.py`, with a thin script entrypoint) is the sole author
of capsule inputs, in two passes. Pass one resolves the target-selective Python
closure from the committed `uv.lock` through the existing wheel-target
primitive and the ACP closure from the committed `package-lock.json`, acquires
every wheel, tarball, external-license blob, and pinned source into the
sha256-keyed content-addressed input cache (verifying each byte against its
committed pin), derives per-package license identity - expression, license
members, redistribution evidence - from wheel metadata and tarball contents,
and emits the canonical closure inventories. **Wheel selection:** beside the
compatibility predicate, a pure selection function is the single authority
answering which admitted wheel ships. It adopts the standard installer
tag-priority model rather than a bespoke ordering: for each target it derives a
deterministic ordered supported-tag list from the pinned `packaging` dependency
- `cpython_tags` then `compatible_tags`, called with an explicit `(3, 13)`
interpreter version and an explicit per-target platform sequence derived from
the same fixed baselines the compatibility authority encodes - and ranks every
lock wheel by the best index any of its tags reaches, shipping the lowest. Ties
break by build tag descending, then filename ascending, so selection is a total
order over the lock. This reproduces host-independently the choice a baseline
target machine's installer would make: version-specific compiled wheels over
stable-ABI wheels, higher satisfied stable-ABI floors over lower,
architecture-specific over `universal2`, higher satisfied glibc floors
(`manylinux_2_28`) over lower (`manylinux2014`), pure-Python `py3-none-any`
last. **Curated license overrides:** one committed overrides input, every entry
keyed by package name and exact locked version, with two entry kinds. An
*expression override* supplies the curated SPDX expression for a package whose
wheel metadata lacks `License-Expression`, and carries its evidence: the
verbatim legacy declaration it interprets (legacy license field, OSI
classifier, or an upstream locator at an immutable ref) plus a one-line
justification for any judgement call. An *external license artifact*
additionally binds license bytes for a package shipping none, committing URL,
sha256, and the declared member name the bytes install as. Curated expressions
record upstream's grant faithfully as a valid SPDX expression: a disjunction is
preserved, never collapsed to an elected branch - branch election is
redistribution policy, not package identity - and the capsule carries the text
of every license an expression references. External artifacts are sourced, in
preference order, from a hosted file of the exact locked release on the package
index, an upstream repository URL at a full immutable commit hash, or, only
when no stable upstream URL exists, a copy vendored beside the overrides input;
in every case the committed sha256 is the integrity authority, verified before
caching, so acquisition can never introduce unreviewed content. **ACP curated
overrides:** the npm license contract mirrors the wheel curated fallback. An ACP
package whose `package.json` `license` field is not a canonical SPDX expression -
in particular the `SEE LICENSE IN <file>` reference form - is resolved by a
curated override that supplies the SPDX expression (a standard identifier, or an
SPDX `LicenseRef-` custom reference for a proprietary license) and binds the
referenced license file as the package's license member; the ACP verifier
accepts the curated expression in place of verbatim `package.json` equality
exactly as the wheel verifier accepts a curated expression when metadata carries
none. The required Anthropic SDK packages are the motivating case: their
`package.json` declares `SEE LICENSE IN LICENSE.md`, and their bundled
`LICENSE.md` is a proprietary "all rights reserved" grant deferring to Anthropic's
external commercial terms, so they are recorded as `LicenseRef-Anthropic-Commercial`
with that `LICENSE.md` bound and shipped as the license member. Bundling and
offline redistribution of the proprietary SDK is authorized by the owner under
those commercial terms; this record captures the license identity faithfully and
does not itself adjudicate the commercial grant. Pass two opens
verified archive sessions, invokes the production installed-inventory builder
against the layout authority, authors the digest-pinned capsule input
descriptor naming every artifact including the installed inventories, and hands
the descriptor path and digest to the consumer. This authority is the only
production constructor of closure inventories and descriptors and the only
component permitted network access. **Build script:** a read-only consumer: it
opens the verified input session against the prepared descriptor and digest,
derives the assembly plan, materializes the installed tree into one
caller-owned unpublished generation with the capsule archive and manifest
beside it, and emits the descriptor and its digest into the generation's
published evidence; it acquires nothing, derives nothing, and mints nothing. **Materializer (`S103`):** consumes only the plan and the v2 inventories,
streaming each record's `source_member` from the archive named by
`source_sha256` through the leased nested-parent write path and verifying size
and sha256 during the write; reconciliation is byte-exact because the inventory
is the layout at materialization time. Interpreter subtrees keep verbatim
projection; `S14`/`S15` verify and publish the same declarations.

## Rationale

The chosen shape makes the declared tree and the written tree the same
artifact. Provenance inside the file record turns reconciliation from tree-
diffing into per-record proof and lets validation bind file, license, and
source identity atomically where the model already validates cross-record
facts. Extending the existing inventory rather than adding a sidecar keeps one
loading, descriptor, and join path. Deriving installed digests from the
already-proven `RECORD` evidence avoids a second trust root. Keeping the generic
projector's wheel refusal preserves the fail-closed boundary that motivated it
while supplying the spec-conformant path the refusal always implied
(`2026-07-18-desktop-product-profile-adr`;
`2026-07-21-capsule-install-layout-reference`).

## Consequences

- `W01.P03.S103` gains a complete implementation target: layout module, v2
  inventory with builder, and a record-replaying materializer; `S13`/`S14`/`S15`
  consume the same declarations for build, verification, and publication.
- The fixture-authored v1 inventories and every test fixture must migrate to v2
  with real provenance; the version-literal change is intentionally breaking so
  no unprovenanced inventory can pass reconciliation.
- The `.data` audit is live, not hypothetical: the current lock's real selected
  set trips the guard on three required packages (`greenlet` headers on all four
  targets; `jsonpatch`/`jsonpointer` `#!python` scripts on all four; `pywin32`
  scripts on Windows). The materializing layout must therefore implement the
  drop rule before `S13` can materialize this closure; a follow-up step changes
  `install_layout.py` from reject-scripts/headers to drop-scripts/headers with
  per-member evidence, and re-audit is required whenever the lock changes since
  a future wheel could introduce a still-fail-closed `.data/data` key.
- Remaining fail-closed `.data` handling may reject a future locked dependency; relaxing
  requires a closure audit and an amendment here, not an ad-hoc bypass.
- The Windows launcher is unblocked as a stub-plus-generated-payload
  concatenation; the launcher contract, manifest schema, and golden vectors are
  unchanged. The materializing Step must add the stub asset to the input cache,
  replace its fail-loud Windows refusal with the generator, and prove one
  composed launcher by live execution on Windows; the stub's
  relocatable-shebang behavior is documentation-verified until that run. The
  single vendored binary is architecture-specific: a future Windows arm64
  target requires its own stub asset through the same mechanism. Unsigned
  launcher executables share the antivirus-flagging exposure of every
  pip-installed script; code signing is not decided here.
- Inventory bytes grow by two provenance fields per record within existing
  bounds; the dashboard-visible tree digest is unaffected.
- The layout authority becomes the single place wheel/npm placement can change;
  any parallel placement logic in build or verify scripts is a defect by
  definition.
- The build, verify, and publish stages flip output contract together: the
  verifier is wired to the legacy single-archive layout and the workflow chains
  build, verify, and publication, so the three stages land as one set (with
  preparation preceding them); landing the build rework alone yields an
  unverifiable artifact and a red workflow by construction.
- The retention envelope of the input session (512 snapshots, 8 GiB) has no
  supported-target proof; the preparation authority's first real closure run
  for each target is that proof and must pass - or force a revision here -
  before the build rework lands.
- The first real license sweep across the locked closure will surface packages
  without a metadata license expression; each needs a curated override with
  recorded evidence before its target capsule can build. This is deliberate
  fail-closed cost, not a defect.
- The measured sweep bounds the initial curation cost: 34 of 84 distinct
  packages need an expression override, four of which also need an external
  license artifact because their wheels ship no license bytes at all; three
  further packages carry a legacy-recognizable member the verifier's existing
  path accepts without curation. Each entry is a one-time reviewed fact that
  recurs only when its package's locked version changes.
- The first-party project wheel installs into the Python closure but is not a
  third-party license concern. The vaultspec-a2a distribution wheel is a full
  installed member of the Python closure inventory - its modules back the two
  contract console-scripts, so it is materialized and provenance-bearing like
  every other wheel - yet it is not a member of the uv.lock dependency closure
  and carries no third-party attribution entry in the `.capsule-licenses`
  bundle. Its own license ships as the ordinary archive-root
  `dist-info/licenses/` member the layout places verbatim; the third-party
  compliance index is for redistributed dependencies only. The
  dependency-license-coverage gate therefore stays strict - every dependency
  must present a source-verified license - while treating the first-party
  project wheel as the one legitimate installed package outside the dependency
  closure. This keeps the coverage guarantee intact without a decorative,
  unverified license record for the product's own wheel.
- The ACP closure carries a proprietary dependency: the required Anthropic SDK
  packages ship an "all rights reserved" `LICENSE.md`, so the capsule bundles a
  non-open-source component recorded as `LicenseRef-Anthropic-Commercial`, with
  that notice shipped inside the capsule. The shippable capsule therefore
  depends on the owner's authorization to redistribute the SDK under Anthropic's
  commercial terms; that authorization is a standing input to this record, not a
  fact it can derive. Extending the ACP license contract to accept a curated
  override for a non-SPDX `package.json` license is the mechanism that lets this
  and any future non-SPDX-declaring ACP dependency reconcile without weakening
  the verifier for the SPDX-clean majority.
- On the measured lock the previously untied packages resolve to their compiled
  variants - `sqlalchemy` to its cp313 platform wheels over `py3-none-any`,
  `cryptography` to cp311-abi3 on `manylinux_2_28`, and `charset-normalizer`,
  `websockets`, `wrapt`, and `regex` to architecture-specific wheels - removing
  both the pure-Python performance regression and the `universal2` size
  doubling.
- The installed-inventory builder's invocation moves from the build script to
  the preparation authority; the build script's role narrows to consumption,
  which supersedes the earlier phrasing that the build script invokes the
  builder.
