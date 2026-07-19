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
