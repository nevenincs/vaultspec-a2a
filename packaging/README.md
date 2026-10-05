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
licenses and explicit ELF dependencies under the onedir's `isolation/`.
The Linux build host needs a C compiler, make and a static C-library toolchain.
Sources are fetched during assembly, never during a provider launch. The shipped
manifest attests the staged bytes; a changed or missing input refuses execution.

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
a fallback resolver. Custom hosts/NSS, proxy and CA policy still need qualification.

The explicit `packaging/tests/native_isolation_artifact.py` controls run after a
real Linux build. Set `VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE` to the onedir and
`VAULTSPEC_A2A_TEST_LINUX_NODE` to the declared Node executable, whose ELF
dependencies must have been supplied to assembly. Invoke the file directly with
the locked test environment. These controls exercise relocated frozen execution,
project I/O, synthetic role access, private-state denial, artifact refusal,
system/DNS-only/child hostname lookup, an HTTPS checksum download, read-only resolver
data and detached-child cleanup. Network controls require access to nodejs.org;
they do not establish provider login or turn eligibility.
