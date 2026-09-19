"""What initializing THIS repository means.

The only file in :mod:`dev.init` that differs between repositories. Everything
here is data: the host tools the workstation must already provide, the steps
each phase runs, and - the part that is easy to get wrong - the inputs whose
change makes a phase stale and the artifacts whose absence does the same.

``vaultspec-a2a`` had no entry point at all. Provisioning a worktree meant
running five commands from two different sections of the README in the right
order - ``just doctor-check``, ``just deps-tooling``, ``just deps-node``,
``just vault-setup``, ``just hooks-install`` - and knowing which of them
were optional. Each of those recipes remains; `init` selects the needed phases.

`.env` is materialized as a preflight, on every entry point including
``init-python``. The reason has changed and the step has not. It was once the
`dotenv-load` trap: the justfile loaded `.env` before running anything, so a
worktree without one was under-configured for the very command that would have
created it. That blanket load is gone - credentials now reach only the commands
whose scope declares them, through :mod:`dev.credentials`. What remains is that
`.env` is where those scopes READ from, so a worktree without one starts its
services on defaults and refuses the scopes with required names. Materializing
it first is still the right move; it is now a precondition for the credential
scopes rather than for `just` itself.

Stdlib-only, by the constraint stated in :mod:`dev.init`.
"""

from __future__ import annotations

import sys
from typing import Final

from dev.init.contract import Phase, Step
from dev.init.probe import Requirement

#: The ephemeral interpreter `init` is running on. Steps that are themselves
#: Python reuse it rather than assuming a `python` on PATH, because the whole
#: premise of this package is that the environment does not exist yet.
PY: Final = sys.executable

#: The environment-resolving prefix. Unlike every gate in this repository these
#: steps deliberately do NOT carry `--no-sync`: changing the environment is
#: their entire purpose.
TOOLING: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "--no-sync",
    "--frozen",
    "--no-default-groups",
    "--group",
    "tooling",
)

#: What the workstation must provide before `init` can do anything.
#:
#: `.node-version` and `package.json`'s `engines` field are the authority on
#: the Node version, not the README - they disagreed, and a version check that
#: reads a prose file is not a check. `dev/node/check_node_version.mjs` is the
#: precise arbiter and runs as a step; full setup also checks the host version
#: before trusting an existing phase stamp.
REQUIREMENTS: Final[tuple[Requirement, ...]] = (
    Requirement(
        command="uv",
        purpose="It resolves every locked dependency profile.",
        install_url="https://docs.astral.sh/uv/getting-started/installation/",
    ),
    Requirement(
        command="node",
        purpose="It hosts the pinned Claude ACP runtime the worker executes.",
        install_url="https://nodejs.org/",
    ),
    Requirement(
        command="npm",
        purpose="It restores package-lock.json.",
        install_url="https://nodejs.org/",
    ),
    Requirement(
        command="docker",
        purpose="Only container build and stack recipes need it.",
        install_url="https://docs.docker.com/engine/install/",
        advisory=True,
    ),
)

#: Steps that run before any phase, on every entry point. Materializing `.env`
#: belongs here rather than in `init-tools` because a worktree without one is
#: under-configured for every tool that reads it - and in this repository that
#: now means the credential scopes in :mod:`dev.credentials`, which resolve the
#: service and compose variables out of exactly this file.
PREFLIGHT: Final[tuple[Step, ...]] = (
    Step(
        name="dotenv",
        argv=(PY, "-m", "dev.init.dotenv", ".env.example", ".env"),
        summary="Provision .env from .env.example when it is absent.",
    ),
)

PYTHON = Phase(
    name="python",
    summary="Resolve the locked tooling and server dependency profiles into .venv.",
    steps=(
        Step(
            name="uv-venv",
            argv=(PY, "-m", "dev.init.venv", ".venv"),
            summary="Create the virtual environment, leaving an existing one alone.",
        ),
        Step(
            name="uv-sync-tooling",
            # The `dev` dispatcher itself runs out of this profile, so it must
            # exist before any other `python -m dev` step can be attempted.
            argv=(
                "uv",
                "sync",
                "--locked",
                "--no-default-groups",
                "--group",
                "tooling",
            ),
            summary="Install the repository tooling profile the dispatcher runs on.",
        ),
        Step(
            name="uv-sync-all",
            argv=(
                "uv",
                "sync",
                "--locked",
                "--no-default-groups",
                "--extra",
                "server",
                "--group",
                "all",
            ),
            summary="Install the server extra and the composed development group.",
        ),
    ),
    inputs=("uv.lock", "pyproject.toml", ".python-version"),
    artifacts=(".venv",),
)

NODE = Phase(
    name="node",
    summary="Restore the project-pinned Claude ACP runtime from the npm lock.",
    steps=(
        Step(
            name="node-version",
            argv=("node", "dev/node/check_node_version.mjs"),
            summary="Verify the running Node satisfies .node-version and package.json.",
        ),
        Step(
            name="npm-ci",
            argv=("npm", "ci"),
            summary="Install node_modules exactly as package-lock.json pins it.",
        ),
    ),
    inputs=("package-lock.json", "package.json", ".node-version"),
    artifacts=("node_modules",),
)

TOOLS = Phase(
    name="tools",
    summary="Enroll the Vaultspec workspace and install the prek hook.",
    steps=(
        Step(
            name="vault-enroll",
            argv=(*TOOLING, "python", "dev/vault/enroll.py"),
            summary="Enroll every Vaultspec Core provider projection in dev mode.",
        ),
        Step(
            name="hooks-install",
            argv=(
                "uv",
                "run",
                "--no-sync",
                "--frozen",
                "--no-default-groups",
                "--group",
                "dev",
                "python",
                "-m",
                "dev.repo.hooks",
                "install",
            ),
            summary="Install the repository-managed, path-agnostic prek hook.",
        ),
        Step(
            name="doctor",
            # Diagnosis, not a gate: it reports Docker as optional and is the
            # last word a person wants after a successful provisioning.
            argv=(*TOOLING, "python", "-m", "dev.doctor", "check"),
            summary="Diagnose required tools and optional Docker support.",
            advisory=True,
        ),
    ),
    inputs=("uv.lock", "dev/vault/enroll.py"),
    artifacts=(".vaultspec/providers.json",),
)

#: The phases, keyed by name. The runner reads this and nothing else.
#:
#: `just rag-setup` is deliberately absent. The RAG bridge is an optional
#: extra whose enrollment is a separate decision, and pulling it into `init`
#: would make every worktree pay for a capability most of them never use.
PHASE_PLAN: Final[dict[str, Phase]] = {
    "python": PYTHON,
    "node": NODE,
    "tools": TOOLS,
}
