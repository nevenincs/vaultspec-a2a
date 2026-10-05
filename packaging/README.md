# Packaging

This product freezes a PyInstaller onedir per target (`pyinstaller/`, driven by
`.github/workflows/release.yml`) and attaches it to a GitHub Release.

## There is deliberately no Scoop bucket and no Homebrew tap here

Every other product on this account ships package-manager channels from its own
repository — vaultspec-core and vaultspec-rag each carry `bucket/` and `Formula/`,
and cadrumo publishes into the shared `nevenincs/homebrew-tap`. Their absence here
is a decision, not an oversight, and this file exists so that it is not later
mistaken for a gap and "fixed".

vaultspec-a2a is not an independently installable end-user product. It is a
**component** consumed by the dashboard, which owns runtime selection and
installation. Its generic product composer can place the entire onedir beneath
`a2a/`; its current product-release workflow omits that optional component and
resolves A2A from a separate runtime generation. Producing an archive here does
not establish that a particular dashboard generation embeds or qualifies it.

A Scoop manifest or a Homebrew formula here would publish a second, separately
installable copy of the runtime, which is precisely the split release set that
constraint forbids. A user who installed it would end up with a runtime the
dashboard neither pinned nor manages.

If A2A ever becomes a standalone product, the channels belong with it — and the
generator to copy is `vaultspec-core/dev/packaging`, which is shared verbatim with
vaultspec-rag apart from its per-product `products.py`.

## Release-path note

`release.yml` schedules all four native freeze targets onto self-hosted runner
labels. Fleet readiness must be checked when cutting a release; this document
does not assert the current registration or availability of those runners.

## Linux isolation assets

`scripts/build_binary.py` builds a static bubblewrap 0.11.1 helper from
hash-pinned upstream bubblewrap and libcap 2.75 sources, then stages the helper,
licenses, explicit ELF dependencies and the frozen Certifi certificate bundle
under the onedir's `isolation/`.
The Linux build host needs a C compiler, make and a static C-library toolchain.
Sources are fetched during assembly, never during a provider launch. The shipped
manifest attests the staged bytes; a changed or missing input refuses execution.
The certificate bundle comes from the locked dependency in the actual onedir,
is validated during assembly and is mounted read-only at
`/etc/ssl/certs/ca-certificates.crt`. No host certificate directory is mounted.

The frozen launcher locates that exact component directory beneath its captured
capsule root. The capsule still holds the separate Node/npm assets. A2A's frozen
ELF closure alone does not qualify those provider assets; a composer can supply
each additional trusted ELF through repeated `--isolation-executable PATH`
arguments when building A2A. Actual provider authentication, actor IPC, network
compatibility and completed-turn evidence remain required before desktop admission.

Each Linux launch acquires the host-selected `/etc/resolv.conf` through trusted,
nonfollowing descriptors and supplies only validated DNS settings as a sealed,
read-only child file. The source directory is absent from the child. Sources must
be root-owned regular files with one link and safe permissions; only the explicit
systemd, NetworkManager and WSL resolver aliases in the implementation are accepted.
The WSL alias supports the research host and adds no production WSL requirement.
Missing, unsafe, changing or unsupported resolver settings refuse execution without
a fallback resolver. Custom hosts/NSS, proxy and additional CA policy still need
qualification.

The explicit `packaging/tests/native_isolation_artifact.py` controls run after a
real Linux build. Set `VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE` to the onedir and
`VAULTSPEC_A2A_TEST_LINUX_NODE` to the declared Node executable, whose ELF
dependencies must have been supplied to assembly. Invoke the file directly with
the locked test environment. These controls exercise relocated frozen execution,
project I/O, synthetic role access, private-state denial, artifact refusal,
system/DNS-only/child hostname lookup, an HTTPS checksum download using the staged
certificate bundle, read-only resolver and certificate data, and detached-child
cleanup. Network controls require access to nodejs.org;
they do not establish provider login or turn eligibility.

The separate `packaging/tests/native_provider_lifecycle.py` controls require a
genuine Linux Codex package and an already selected login in addition to those
artifact inputs. Set `VAULTSPEC_A2A_TEST_LINUX_CODEX_TREE`,
`VAULTSPEC_A2A_TEST_CODEX_HOME` and `VAULTSPEC_A2A_TEST_CODEX_MODEL` explicitly.
The model must come from that provider's actual catalog. These controls perform
real work and check immediate process and temporary-home cleanup after completed
streams, early close, cancellation, interruption, concurrent turns and beta event
streams. Invoke the file explicitly with the locked test environment; keep login
material outside the repository. Passing these controls does not establish full
gateway/actor integration or eligibility on another target.
The same file also drives the real catalog factory through authenticated
discovery, an owned invalid-executable refresh failure, backoff and recovery.
It checks that stale enumeration survives while historical login and transport
health are cleared until a fresh successful observation.
Public configuration, type and synchronous-listener binding controls also check
joined early closure and cancellation, callbacks, argument/configuration merging
and beta event-resource behavior. Direct model `bind()` and other Runnable
wrappers still need separate qualification; these controls do not qualify every
LangChain streaming surface.
