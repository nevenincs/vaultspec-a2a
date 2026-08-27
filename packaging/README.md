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
**bundled component** of the composite dashboard product: the dashboard executable
and the adjacent A2A runtime ship as one release set, and the dashboard's own
packaging carries the ADR constraint that *every supported channel installs the
same logical release set*
(`vaultspec-dashboard/packaging/a2a-support-matrix.json`). The runtime onedir built
here is consumed by that composition — it is pinned by
`vaultspec-dashboard/packaging/a2a-component.lock.json` and placed into the
offline-complete tree by the product installers.

A Scoop manifest or a Homebrew formula here would publish a second, separately
installable copy of the runtime, which is precisely the split release set that
constraint forbids. A user who installed it would end up with a runtime the
dashboard neither pinned nor manages.

If A2A ever becomes a standalone product, the channels belong with it — and the
generator to copy is `vaultspec-core/dev/packaging`, which is shared verbatim with
vaultspec-rag apart from its per-product `products.py`.

## Release-path note

This repository currently has **no registered self-hosted runners**, while
`release.yml` schedules its freeze matrix onto `${{ matrix.runner }}` labels. The
v0.1.0 and v0.2.0 releases were built when runners were registered; as things stand
a new release would queue rather than fail. That is a fleet-state issue rather than
a packaging one, but it is recorded here because it is invisible from the workflow
file alone.
