---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` audit: `W01 P01 S01 dependency profile review`

Status: PASS

## Scope

Reviewed only the S01 changes to `pyproject.toml` and its Step Record against
the accepted desktop product profile. Concurrent lockfile, authoring, provider,
test, preset, database, and scratch changes were excluded.

## Findings

### default-otel-import | high | Moving the OTLP exporter to server breaks default telemetry initialization

Gateway and worker startup both invoke `configure_telemetry`. Its `_check_otlp`
probe calls `importlib.util.find_spec` on the nested OTLP exporter module without
handling a missing `opentelemetry.exporter` parent. A real isolated environment
containing `opentelemetry-sdk` without the exporter reproduced
`ModuleNotFoundError`. The default metadata resolves but is not yet runnable.

### torch-source-portability | medium | The CUDA source override is uv-project metadata rather than wheel-extra metadata

The `extra = "rag"` selector correctly scopes uv lock resolution, but
`tool.uv.sources` is not emitted as wheel `Requires-Dist` metadata. Ordinary
wheel consumers receive the Torch extra without the custom index. The capsule
must therefore consume the uv-managed lock, and the Step Record must not claim
that wheel metadata alone carries the override.

## Recommendations

- Keep S01 open and route the high-severity telemetry issue to the executor.
- Guard optional OTLP detection without retaining the exporter in the desktop
  base, then prove gateway and worker telemetry initialization from a real clean
  base installation.
- Narrow the CUDA statement to uv-managed source and locked capsule resolution.

## Resolution log

- Added plan Step `S93` through the plan CLI immediately after S01 to own the
  optional OTLP guard and clean-base runtime proof.
- Updated the S01 Step Record to state that the CUDA source override is uv
  project metadata used by the locked capsule and is not published in wheel
  `Requires-Dist` metadata.
- Implemented S93 with ordered parent-namespace probing and no exception catch,
  preserving visible failures from installed but broken exporters.
- Proved the gateway and worker production telemetry bindings from a real
  default-only installation with the exporter namespace absent.

## Follow-up review

The S93 remediation and corrected S01 record passed independent review. No
critical or high findings remain, and both S93 and S01 may close.

### probe-gate-durability | medium | Preserve the clean-base regression proof as a durable gate

The S93 probe is an executable real-behavior harness, not a pytest-collected
test or registered quality task. Its installed module invocation will also
become unavailable when packaged tests are excluded. This does not invalidate
the clean-install evidence for S93, but S05 must register an external harness
against the installed production package or replace it with equivalent
installed-metadata coverage.

Follow-up verification reproduced the default-only clean installation, both
gateway and worker profiles, all 29 focused telemetry tests, the installed
exporter branch, Ruff, formatting, targeted type checking, lock consistency,
and the default, server, and RAG export closures.

## `W01 P01 S02` lock review

Status: PASS

The regenerated lock is deterministic and retains 171 package identities,
versions, and sources. Two isolated non-upgrading regenerations from committed
metadata produced the same bytes, and the repository lock check passed under
CPython 3.13.

Default and server dry-runs passed for all five accepted targets. Exported
closure inspection confirmed that the desktop base contains neither server nor
RAG packages, the server extra restores only its declared capability, and RAG
remains separate. Intel macOS's locked `cryptography` source build belongs to
the later capsule assembly and native certification gates. The recorded Torch,
macOS, and manylinux limits apply to the ADR-excluded optional RAG capability,
not to the mandatory desktop base.

The initial review identified one low-severity Step Record overstatement: uv
also normalized transitive environment markers for CUDA and NVIDIA packages,
Torch, and `phart`, rather than changing only root dependency classification.
The record now discloses that normalization while preserving the verified fact
that no package identity, version, or source changed. Follow-up review passed.

## `W01 P01 S03` Node lock review

Status: PASS

No findings were identified. The existing canonical lock pins the sole root
adapter dependency to exact `@agentclientprotocol/claude-agent-acp` 0.59.0,
requires Node 22 or newer, and records the SDK 1.2.1 archive plus resolved URLs
and integrity metadata throughout the production closure. The predecessor Zed
identity and versions 0.23.1 and 0.20.2 are absent.

Two isolated lock regenerations, an engine-strict clean installation, a dry-run
installation, and real production factory classification preserved the tracked
lock digest and selected the installed project-local adapter entrypoint. The
lock bytes already entered history in commit `a7896cc`; a record-only adoption
is therefore correct and avoids manufacturing a no-op lock diff. Capsule-owned
adapter resolution and removal of source-checkout installation guidance remain
assigned to the later package-authority step.

## `W01 P01 S04` runtime-acquisition review

Status: PASS

The new typed resolver keeps non-desktop behavior unchanged and makes desktop
selection return a stable, path-free unavailable-capability result instead of
an executable launch specification. Desktop policy filters launch arguments,
autonomous tool names, Claude and project configuration, Codex configuration,
and model composition. It also removes stale runtime-acquired entries while
preserving unrelated authoring state.

Initial independent review required two revisions. First, desktop admission
accepted contradictory metadata that marked an entry both desktop-available
and runtime-acquired. Admission now requires explicit availability together
with explicit `runtime_acquisition=false`, and omitted or contradictory values
fail closed. Second, an empty current declaration returned before cleaning
pre-attached ACP or Codex RAG state. Desktop cleanup now runs for that case,
while the non-desktop empty declaration remains the prior identity no-op.

Follow-up review passed with no remaining findings. Nine focused tests use the
production resolver and real ACP and Codex model objects; the impacted provider
and configuration suites, Ruff, and scoped type checking also pass. Application
selection of the desktop policy remains explicitly assigned to S16, so this
step does not claim end-to-end desktop runtime closure.

## `W01 P01 S05` installed dependency-closure review

Status: PASS

The source-side certification gate builds the real production wheel, exports
the locked base, server, and RAG closures, installs the base closure and wheel
into an isolated CPython 3.13 environment, and checks the installed graph with
`uv pip check`. Its isolated child interpreters import the installed gateway
and worker entrypoints rather than a packaged test module. Both initialize the
OpenTelemetry SDK with the expected service identity while the optional OTLP
exporter remains absent.

The built and installed metadata agree on exactly the `server` and `rag`
extras. The direct server roots are exactly AsyncPG, the Postgres LangGraph
checkpointer, the OTLP gRPC exporter, and Psycopg; the direct RAG roots are
exactly Torch and `vaultspec-rag`. The installed base is disjoint from every
package added only by the optional closures. Server resolution passes on the
native interpreter, while RAG resolution is deliberately bounded to the
supported CPython 3.13 x86-64 Windows target and preserves S02's recorded
manylinux and macOS limitations.

Initial architecture review required locked rather than frozen export
validation, exact optional-root assertions, target-bounded RAG resolution,
marker-aware installed-environment validation, and removal of mechanically
guaranteed success assertions. A transitive parser import was replaced with an
explicit dev-only `packaging` declaration. The resulting lock change affects
only root-project dev metadata: all 171 package records and the published base,
server, and RAG closures retain their prior identities and fingerprints.

Independent follow-up review found no unresolved critical, high, or medium
issues. Five real-artifact tests, the combined 34-test telemetry and desktop
suite, Ruff, formatting, scoped type checking, focused dependency lint, and
`uv lock --check` pass. The source-side test package is still present in the
current wheel; excluding it is explicitly owned by S06 and must be verified
from the built artifact by S12. Because the probe imports only installed
production modules, that later exclusion will not weaken this regression gate.

## `W01 P02 S06` production wheel-shape review

Status: PASS

The repaired Hatch target packages the production Python tree and its required
resources while excluding every ordinary test tree, `desktop_tests`,
`service_tests`, package-level `conftest.py`, VidaiMock tapes, mock agent and
team presets, and the deterministic ADR acceptance preset. A clean commit
archive produces a 228-entry wheel with 224 package entries while retaining all
11 migration assets, nine production agent presets, two production team
presets, and the bundled context rule.

Initial architecture review found a high-severity closure and evidence defect.
The first exclusion list missed the root pytest configuration and 13
`service_tests` files, while its archive check only searched literal `tests`
and `desktop_tests` paths. Its recorded counts also came from a dirty worktree
that contributed an untracked preset, so the claimed 269-entry artifact was not
the committed source artifact. Review additionally found certification-only
mock and deterministic resources in the desktop product wheel.

The target now states Hatch's actual behavior: every non-excluded file below
the package root can enter the artifact, including untracked files in a dirty
build. Verification therefore builds from a clean commit archive. Product
packaging excludes certification resources without deleting them or changing
source and Compose workflows. The installed desktop preset inventory is the
curated artifact inventory; S08 owns only the package-resource loading seam,
and S12 must enforce the exact installed production discovery set as part of
its clean-artifact contract.

Independent follow-up review reproduced the clean counts and found no remaining
critical, high, or medium issues. The S05 real-wheel dependency gate remains
five-for-five, TOML parsing confirms the exact 14 exclusions, Ruff and lock
checks pass, and the required migration, production-preset, and context assets
remain present. S10 must move or force-include its repository-root schema, and
S12 must reject dirty or forbidden archive content by exact identity.

## `W01 P02 S07` package-owned migration review

Status: PASS

The runtime migration configuration now resolves Alembic's `env.py`, revision
scripts, and template from the installed `vaultspec_a2a.database.migrations`
package. It attaches no checkout-level `alembic.ini`, preserves the existing
developer CLI configuration separately, and completes a clean-wheel migration
from an unrelated working directory through revision `0007`.

Initial independent review found two high-severity defects. Alembic stores main
options through an interpolating parser, so a literal percent sign in either the
installed script path or database URL failed before startup. In addition,
concurrent async callers dispatched Alembic into separate threads even though
its command proxy is process-global; real two-database probes cross-wired the
contexts and left missing or partially stamped databases. Review also found a
medium error-contract gap for missing package resources.

Both configuration values are now escaped only for Alembic storage and round
trip to their original values. The synchronous command is serialized by a
process-wide lock acquired inside the worker thread, preserving event-loop
responsiveness while protecting Alembic's global context. Missing or incomplete
package resources produce a stable, path-safe `FileNotFoundError`, and the new
configuration builder is included in the module's public API.

Follow-up review found no unresolved critical, high, or medium issues. Fifteen
focused migration tests and all 118 database tests pass, including a real
SQLite database beneath a percent-containing directory, encoded SQLite and
PostgreSQL configuration round trips, and concurrent upgrades of two distinct
databases. Ruff, formatting, and scoped type checking pass. The tests import
production code and exercise real package resources and databases without
fakes, mocks, stubs, patches, skips, or mirrored migration logic.

## `W01 P02 S08` package-owned preset review

Status: PASS

The preset-loading seam now derives bundled agent and team directories from the
installed `vaultspec_a2a.team` package resource. Workspace overrides retain
their precedence, and source and Compose profiles retain their wider preset
inventory. Desktop product curation remains the S06 packaging authority; no
dashboard-side preset filter exists or is required for the clean capsule.

Independent review installed the clean S06 wheel into isolated CPython 3.13.
The resource authority resolved beneath `site-packages`; discovery returned
exactly nine production agent presets and two production team presets, no mock
or deterministic certification id, and real workspace override and missing-id
behavior remained correct. All 120 team tests, Ruff, formatting, and scoped
type checking pass.

The original Step Record incorrectly said a product-layer selection filter
removed source-side mock ids. The record and module documentation now state the
actual boundary: the desktop wheel excludes certification resources, while the
loader reads whatever valid inventory its installed package contains. S12 must
retain this clean-installed inventory proof. No unresolved critical, high, or
medium issue remains.

## `W01 P02 S09` capsule-owned provider asset review

Status: PASS

The default Node-backed ACP classifier now has one explicit capsule-assets
authority. When configured, it resolves production-owned Node and ACP relative
identities into absolute canonical files and never falls back to the checkout
or `PATH`. Omitted capsule-root selection consults settings; explicit `None`
retains the Compose and project-local classifier. The later desktop profile step
remains responsible for activating this seam.

Initial review found three high-severity boundary defects: relative roots yielded
working-directory-sensitive commands, file symlinks or directory junctions
could escape the lexical capsule root, and tests duplicated the production
platform/layout rules. It also found an error-contract gap where unknown-user
expansion could leak `RuntimeError`. The repair moves all layout identities into
production, canonicalizes the root and files, rejects resolved files outside the
canonical authority, distinguishes omission from explicit `None`, and guards
both user expansion and strict resolution behind actionable `ConfigError`.

Independent follow-up reproduced real Windows file-symlink and directory-junction
escape rejection and found no unresolved critical, high, or medium issue. Ten
focused real-filesystem tests, the 340-test provider suite, the 82-test control
suite, Ruff, formatting, scoped type checking, and diff checks pass without
fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures.

S09 proves canonical path identity, ownership, presence, and armed no-fallback
behavior. It deliberately makes no readiness or successful-launch claim.
Executable-mode and runnable-artifact certification remains assigned to S14,
which precedes S16 desktop-profile activation.

## `W01 P02 S10` component-manifest contract review

Status: PASS

The A2A package now owns one versioned desktop component-manifest authority and
exports its byte-exact Draft 2020-12 schema at a stable installed resource path.
The contract binds the component identity to the A2A distribution asset, admits
only the five approved target triples and exact four-asset closure, pins CPython
3.13, Node.js 22, and ACP 0.59.0, and gives the gateway and standalone MCP
surfaces distinct schema-visible discriminators. Asset digests describe the
immutable source artifact bytes; later SBOM and dashboard release-set contracts
remain responsible for installed-tree and composite-release integrity.

Initial review found crossed entrypoint kinds could pass schema validation, the
schema was absent from the built wheel, component and distribution versions
could disagree, the API range admitted versions the production router does not
implement, and command segments were not portable across Windows. The repair
introduced typed entrypoints, a schema-visible `v1` API enum, production identity
binding, stable wheel inclusion, and one shared runtime/schema portability
policy. Follow-up review found and repaired the legacy Windows device spellings
`COM¹`/`²`/`³` and `LPT¹`/`²`/`³`.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced 111 focused production-model and Draft 2020-12 tests, the real
working-tree wheel build and isolated installed-resource read, Ruff checking,
Ruff formatting, and scoped type checking. The tests import production code and
use no fake, mock, stub, patch, monkeypatch, skip, expected failure, or mirrored
business logic. S11 remains explicitly open until the emitter consumes these
typed authorities and genuine immutable artifacts.

## `W01 P02 S11` pinned component-manifest emitter review

Status: PASS

The emitter now treats the exact A2A wheel as the sole authority for component
name, version, MIT license expression, console entrypoints, Alembic migration
range, and A2A source-artifact digest. It copies and hashes the wheel once into
a bounded private snapshot, then reads only that snapshot. The other three
assets and both dependency locks remain explicit immutable source-artifact byte
inputs; S13 and S14 retain real runtime acquisition, licensing, SBOM, and
installed-tree integrity.

Initial review found four high-severity provenance/evidence defects: identity
could come from an unrelated distribution, duplicate console scripts collapsed
silently, source-digest semantics were ambiguous, and positive tests fabricated
distribution metadata. It also found producer-specific JSON bytes, unbounded
pre-I/O work, and leaked validation failures. The first repair moved identity
and entrypoint parsing into the real wheel, defined canonical JSON v1, and used
real-wheel evidence.

Adversarial follow-up then reproduced split `.dist-info` authority, unsafe
Windows migration names and alternate data streams, raw migration exceptions,
special-device hashing, late string validation, an independent digest-algorithm
override, and stale license evidence. The final repair binds one root-level
`.dist-info` identity, derives `License-Expression: MIT`, rejects traversal,
devices, ADS, overlong/deep/case-colliding paths, requires regular files at
preflight and descriptor time, normalizes expected failures, and validates
wheel metadata through the production contract before migration materialization
or non-A2A hashing. It also restored and verified the S10 schema force-include
after a concurrent worktree edit removed it.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced 137 focused contract/emitter tests plus the five-test clean
dependency-closure build/install gate, for 142 passes. Ruff checking, Ruff
formatting, scoped type checking, and lock consistency pass. A fresh 608,058-byte
wheel has 235 entries, contains the installed schema resource, one matching
`.dist-info` authority, MIT metadata, both required scripts, and 11 migration
files, while excluding desktop tests. The tests use production code, real wheel
bytes, real locks, and real package migrations without fake, mock, stub, patch,
monkeypatch, skip, expected failure, or mirrored emitter logic.

At S11 closure, S12 remained open because its candidate certification gate
required a separate whole-file architecture review and independent adversarial
verdict. The following section records that later review and repair.

## `W01 P02 S12` clean-wheel component-certification review

Status: PASS

The initial candidate did not meet the architecture boundary even though its
tests passed. It built from the shared dirty checkout, treated the host Node.js
24 executable as a Node.js 22 source artifact, treated a virtual-environment
interpreter and one checkout ACP JavaScript file as complete runtime sources,
and required the local fixture digest to differ from the emitted manifest. Its
fixture-local pin helper also mirrored dashboard rejection logic that does not
yet exist in production.

The repaired gate captures one exact Git commit object, builds the wheel from
that clean archive, and inspects the resulting immutable artifact. It proves the
exact production preset inventory, package-owned migrations, one installed
component-schema resource, standardized Name/version/MIT metadata, and complete
test and certification-preset exclusion. Both the repository schema snapshot
and packaged schema bytes equal the production Pydantic exporter.

The A2A-owned dashboard-shaped JSON is now explicitly `fixture_only`. It binds
only the component name and version to real wheel metadata and validates the
A2A-owned target and digest vocabulary. It does not claim that its digest names
a current emitted manifest, that it is a complete release set, or that it proves
dashboard rejection policy. Real target artifacts and emitted manifests remain
owned by A2A S13 through S15. The dashboard-owned release-set schema, parser, and
producer-consumer proof remain dashboard S04, S06, and S145.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced three focused tests and 145 integrated contract, emitter,
dependency-closure, and component-certification tests. Ruff checking, Ruff
formatting, scoped type checking, lock consistency, and diff hygiene pass. The
tests import production component identity, target, digest, and schema
authorities and use no fake, mock, stub, patch, monkeypatch, skip, expected
failure, or mirrored dashboard consumer logic.

## `W01 P03 S13` deterministic capsule-builder review

Status: REVISION REQUIRED

The builder's static checks and command-line entrypoint pass, and its eleven
service tests collect. Independent review nevertheless found four high-severity
contract failures and one medium-severity evidence gap. S13 must remain open
until these findings are repaired and reviewed. Work begun for S14 does not by
itself close an S13 defect.

### s13-determinism-evidence-contradiction | high | The recorded proof cannot match the manifest contract

Type: release evidence. The record says wheel timestamp bytes and the outer ZIP
change between builds while canonical manifest bytes remain identical. The
manifest includes the exact wheel digest, so changed wheel bytes must change
the canonical manifest. The builder does not set a stable source epoch, and its
test checks canonical bytes rather than complete archive identity. Reproduce
the two-build evidence, bind every nondeterministic input, and require the
claimed artifact boundary to be byte-identical before restoring the claim.

### s13-malformed-digest-fails-open | high | Invalid pins disable verification

Type: supply-chain integrity. Input loading checks only that a digest key is
present. Acquisition verifies bytes only when that value already matches the
expected lowercase SHA-256 grammar. A typo or placeholder therefore accepts
cached or downloaded bytes without verification. A direct real-file probe
reproduced this behavior with `not-a-digest`. Reject invalid digests before any
cache lookup or network access, then compare every acquired byte stream.

### s13-mixed-source-snapshot | high | One capsule can combine HEAD with dirty worktree facts

Type: provenance integrity. The wheel is built from `git archive HEAD`, while
the builder, pin descriptor, exported Python lock, and both dependency-lock
digests come from the live worktree and environment. Build every input from one
exported commit snapshot, or fail closed on index and worktree drift and bind
the commit identity explicitly.

### s13-offline-closure-incomplete | high | The capsule omits transitive runtime payloads

Type: product contract. The capsule carries runtime source archives, the root
A2A wheel, one ACP tarball, and a Python lock recipe. It does not carry the
Python dependency wheelhouse or ACP's transitive npm closure. The artifact
therefore cannot satisfy the ADR's offline-after-install base closure. Assemble
and verify the complete target-native dependency payload before closing S13.

### s13-checkout-free-evidence-incomplete | medium | Locks, licensing, and SBOM cannot be reverified from the artifact

Type: verification adequacy. The manifest hashes checkout lock files that are
not shipped, while the shipped Python lock is not the manifest's bound lock
input. License values are descriptor strings rather than evidence derived from
the acquired artifacts, and no SBOM is present. Ship and digest the actual
closure authorities, validate licensing evidence, and emit the required SBOM
so S14 can verify the capsule without a checkout.

## `W01 P03 S14` standalone capsule-verifier review

Status: REVISION REQUIRED

The verifier detects missing fixed entries, changed root-asset bytes, and
canonical-manifest inconsistency. Independent review found that this is an
internal-consistency check, not the checkout-free closure verifier claimed by
S14. Five high-severity and two medium-severity findings remain open.

### s14-false-closure-certification | high | Root asset names are accepted as an installable offline closure

Type: product contract. Verification does not inspect runtime target identity
or require the Python and ACP transitive payloads missing from S13. A manifest
labeled for Windows can bind another target's runtime archives and still pass.
Require target-native structure and the complete installable dependency payload
before reporting target closure.

### s14-lock-identity-unverified | high | Manifest lock digests cannot be checked from the capsule

Type: provenance integrity. The verifier never checks the manifest's `uv.lock`
or `package-lock.json` identities. Those files are absent, and the shipped
Python lock is not bound by the manifest. Ship the authoritative locks, bind
their bytes, and reject missing, stale, malformed, or mismatched closure state.

### s14-manifest-claims-not-rederived | high | Target, entrypoints, and licenses are trusted assertions

Type: verification adequacy. The command has no expected-target input and only
schema-validates entrypoint and license fields copied from the manifest. It
does not derive those facts from acquired runtime, wheel, and npm artifacts.
Add an explicit target expectation and artifact-derived checks for every claim.

### s14-sbom-incomplete | high | The emitted inventory omits material dependency evidence

Type: supply-chain evidence. The generated inventory contains four top-level
claims and Python package names and versions. It omits Python artifact hashes,
licenses and relationships, all Node and ACP transitive components, and a
standard authenticated SBOM identity. Generate the inventory from the complete
verified closure and validate its schema and digest.

### s14-checkout-free-proof-missing | high | Every test executes through the source checkout

Type: test adequacy. Tests launch the repository script with `uv run` from the
repository root, importing checkout modules and dependencies. Copy or install
the independently pinned verifier and capsule into an isolated directory and
prove verification succeeds with no repository files available.

### s14-archive-ambiguity-unbounded | medium | Duplicate members and resource exhaustion are unchecked

Type: input safety. Converting ZIP names to a set hides duplicate members, and
the verifier applies no entry-count, expanded-size, per-entry-size, or
compression-ratio bounds before whole-entry reads. Reuse the bounded,
duplicate-safe archive discipline from the manifest reader.

### s14-rejection-matrix-incomplete | medium | Explicit failure contracts lack durable tests

Type: test adequacy. Negative coverage omits wrong target, stale lock identity,
malformed lock structure, schema and canonical tampering, entrypoint and license
mismatch, duplicate archive members, resource bounds, and absent transitive
closure. Add real-byte rejection cases for each contract before closing S14.

## `W01 P03 S15` capsule-publication workflow review

Status: REVISION REQUIRED

Full action pinning, concurrency, timeouts, and the five target triples are
sound. Actionlint and independent review found four high-severity publication
blockers and two medium-severity permission and documentation findings.

### s15-intel-macos-runner-invalid | high | The five-target matrix cannot schedule

Type: automation correctness. Actionlint rejects `macos-13` as an unknown
hosted-runner label, so the Intel macOS leg cannot run. Status: resolved by
selecting `macos-15-intel`; Actionlint accepts the complete workflow.

### s15-clean-runner-environment-missing | high | Build scripts run before dependencies are installed

Type: automation correctness. Jobs install uv and CPython, then call
`uv run --no-sync` without creating or synchronizing the project environment.
The scripts require Click, Pydantic, JSON Schema support, and the A2A package.
Status: resolved by synchronizing the locked tooling environment before build
and running each script with frozen no-sync semantics.

### s15-release-gate-bypasses-product-ci | high | Tag publication can ship failed capsule contracts

Type: release safety. The publish job depended only on the capsule matrix. It
was not gated on canonical CI or resolution of the open S13 and S14 findings,
so it could publish an incomplete artifact that passed only internal
self-consistency checks. Status: resolved by removing tag-triggered release
publication. The remaining workflow is manual artifact evidence; release
publication must be added only after repaired capsule certification passes.

### s15-artifact-identity-not-digest-stamped | high | Published assets lack an external immutable binding

Type: supply-chain integrity. Artifact and release names contained only the
target. No outer ZIP digest or checksum asset was published. Status: resolved
for the manual artifact workflow by computing the final archive SHA-256,
including it in the artifact name, and uploading a checksum file beside the
capsule. A future release workflow must preserve this binding.

### s15-workflow-permissions-too-broad | medium | Build jobs inherit release write authority

Type: automation security. Workflow-level `contents: write` applies to all five
build jobs even though they only read source and upload artifacts. Status:
resolved by defaulting the workflow to `contents: read` and granting
`contents: write` only to the publish job.

### s15-release-notes-overstate-artifact | medium | Publication text claims determinism and offline closure

Type: documentation accuracy. Release notes called the ZIP deterministic and
said it contained the locked dependency closure. S13 records differing archive
bytes and ships only a root wheel plus a lock recipe. Status: resolved by
removing release publication and its unsupported notes.
