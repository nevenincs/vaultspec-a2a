# vaultspec-a2a

Headless agent-to-agent orchestration for Vaultspec.

Run agent workflows without a user interface. A gateway accepts HTTP and WebSocket
requests from authoring clients; a separate worker executes the workflows.

[![tests](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-a2a/test.yml?branch=main&style=flat&label=tests&logo=githubactions&logoColor=white&labelColor=24292f&color=57606a)](https://github.com/nevenincs/vaultspec-a2a/actions/workflows/test.yml)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%2B-57606a?style=flat&logo=python&logoColor=white&labelColor=24292f)](https://www.python.org/downloads/)
[![license](https://img.shields.io/github/license/nevenincs/vaultspec-a2a?style=flat&label=license&logo=opensourceinitiative&logoColor=white&labelColor=24292f&color=57606a)](LICENSE)

[Quick start](#quick-start) · [Vaultspec tooling](#enroll-vaultspec-tooling) ·
[Validation](#validate-the-repository) · [Next tasks](#choose-the-next-task) ·
[Ownership](#ownership-model)

The setup below is for a source checkout. To operate the gateway and worker, use
the [operator reference](docs/operations.rst). Semantic search through Vaultspec RAG
is optional.

## Quick start

Install these host prerequisites:

- [Git](https://git-scm.com/)
- [Just](https://just.systems/man/en/packages.html) 1.31 or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Node.js](https://nodejs.org/) 24 with npm, for the pinned Claude ACP runtime
- Docker, only for container workflows

The project requires Python 3.13 or later and currently selects the Python 3.13
series.

```console
git clone https://github.com/nevenincs/vaultspec-a2a
cd vaultspec-a2a
uv python install 3.13
just doctor
just dev deps tooling
just dev deps node
```

`just doctor` verifies the required command-line tools and reports Docker as
optional. The [development guide](docs/development.rst) defines its diagnostic
boundary and remediation paths.

## Enroll Vaultspec tooling

Enroll the repository with the Core version selected by `uv.lock`:

```console
just dev vault setup
```

This installs the locked tooling profile, then enrolls all Vaultspec Core
provider projections in `dev` mode. Core owns its marker-bounded `.gitignore`
block and those projections; canonical inputs and content outside the markers
remain repository-owned and trackable.

If you need semantic discovery, enable the optional RAG bridge:

```console
just dev rag setup
```

This installs the `rag` extra and enrolls RAG in `dependency` mode. The extra
already provides Model Context Protocol (MCP) support. External model and
Qdrant provisioning remains an explicit operation.

Ordinary setup uses committed lock state, never an ambient `latest` release or
machine-global Core/RAG installation. See the [development guide](docs/development.rst)
for diagnosis, dry runs, reconciliation, and deliberate upgrades.

## Validate the repository

Run the canonical tracked-source-safe CI gate:

```console
just ci
```

The gate first synchronizes its locked Python dependency selection and restores
the Claude ACP runtime from `package-lock.json`. It then runs Ruff lint, Ruff
format checking, Ty, Deptry, Actionlint workflow validation, and every test not
marked `service`. It stops at the first failure.

Validate documentation separately:

```console
just dev build docs
```

This runs documentation tests, builds HTML with Sphinx in nitpicky mode, and
treats warnings as errors. The [development guide](docs/development.rst)
defines excluded gates, the separate hosted PostgreSQL migration round trip,
and explicit repair commands.

## Choose the next task

Start with `just help`, then narrow the native command tree with `just dev help`
or `just dev <module> help`.

- Start a caller-owned foreground gateway with `just dev product cli serve`.
- Manage registry-owned host processes through `just dev service ...`.
- Manage Compose-owned stacks through `just dev stack ...`.
- Discover test and build workflows with `just dev test help` and
  `just dev build help`.
- Explore product commands with `just dev product help`.

Focused guides and references:

- [Development setup and validation](docs/development.rst)
- [Operator, process, and stack reference](docs/operations.rst)
- [Architecture and ownership](docs/architecture.rst)
- [Project glossary](docs/glossary.rst)
- [Python API](docs/api/modules.rst)
- [HTTP edge conformance](docs/edge-conformance.rst)
- [Security policy](SECURITY.md)
- [Contribution guide](CONTRIBUTING.md)

## Ownership model

The [architecture guide](docs/architecture.rst) is the canonical ownership map.
Just routes commands, while `vaultspec-a2a` owns product behavior. The process
registry owns named host processes, and Docker Compose (Compose) owns
multi-service stacks. Vaultspec Core owns its provider projections and managed
Git-ignore block. Repair, synchronization, and upgrades are explicit mutations;
bypassing an owner creates conflicting state.

The wider family includes
[Vaultspec Core](https://github.com/nevenincs/vaultspec-core) for the agent
harness, [Vaultspec RAG](https://github.com/nevenincs/vaultspec-rag) for semantic
discovery, and [Vaultspec Dashboard](https://github.com/nevenincs/vaultspec-dashboard)
for a visual interface.

Licensed under the [MIT License](LICENSE).
Report vulnerabilities through the [security policy](SECURITY.md), and read the
[contribution guide](CONTRIBUTING.md) before proposing changes.
