"""Give a command the credentials it needs, and nothing else.

Until now the justfile carried ``set dotenv-load := true``, which loads `.env`
once and injects EVERY variable in it into EVERY subprocess of EVERY recipe.
`.env` holds live provider keys, so `just check-toml` — a TOML formatter — ran
with production API keys in its environment, as did every linter, every type
check, every markdown pass, and every tool any of them spawned. Nothing needed
them; nothing was stopped from reading them.

The replacement is a declared scope. A recipe that genuinely needs credentials
runs its command through this module and names the scope it needs; the scope
lists variables BY NAME, and only those are read out of `.env` and placed in
the child's environment. A recipe that names no scope inherits nothing.

Three rules this module keeps, in order of how badly breaking them would hurt:

*Never reveal a value.* Nothing here prints, logs, or serializes a variable's
value. Presence is the whole question a caller ever asks, and the answer is the
NAME and a boolean.

*Never silently drop a credential.* A variable already set in the environment
wins over `.env`: a caller who exported a key for one command meant it. And a
scope's `required` names are checked BEFORE the command runs, so a missing key
fails as a missing key rather than surfacing eight layers down as an opaque
401 from a provider CLI.

*Never invent a scope.* A command whose credential needs could not be
established keeps the wider scope rather than a guessed narrow one. Losing a
credential a recipe needed is a worse failure than carrying one it did not.

SETTINGS are a separate question from credentials, and this module answers it
once rather than per name. A scope that RUNS the service names this checkout's
`.env` as the operator's settings file, through `VAULTSPEC_A2A_ENV_FILE`; the
service reads it whole from there, so a setting added to `.env.example` reaches
a developer's run without being copied into a list here that would drift out of
date the day it was written. A scope that runs the TEST SUITE names no such
file: the suite declares the environment it runs in, and a developer's `.env`
has no say in it.

Stdlib-only: this runs under the same `--no-default-groups` profiles the
recipes do, and must not add a dependency to any of them.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from dev import runner
from dev.exit_codes import FAILED, OK
from dev.paths import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ENV_FILE",
    "ENV_FILE_VARIABLE",
    "MISSING_CREDENTIAL",
    "SCOPES",
    "Scope",
    "describe",
    "main",
    "missing_required",
    "read_env_file",
    "resolve",
    "run",
]

#: The environment file, at the repository root. Never read for anything but
#: the names a scope declares, and never echoed.
ENV_FILE: Final = REPO_ROOT / ".env"

#: The variable the service reads its operator settings file from. Spelled out
#: rather than imported: this module is stdlib-only, and the name is held to
#: the settings schema by a test rather than by an import the recipes' profiles
#: could not satisfy.
ENV_FILE_VARIABLE: Final = "VAULTSPEC_A2A_ENV_FILE"

#: Exit status for a scope whose required variables are not all present. It is
#: `FAILED` rather than a new number on purpose: a missing credential is a
#: gating result the command reported, not a class of failure the fleet's
#: contract lacks a name for. The message carries the machine-readable detail.
MISSING_CREDENTIAL: Final = FAILED


@dataclass(frozen=True)
class Scope:
    """One named set of variables a command is allowed to receive.

    Attributes:
        summary: What kind of command needs this scope, in one line.
        required: Variables the command cannot work without. Their absence is
            reported before the command runs.
        optional: Variables the command uses when they are present and works
            without when they are not. A provider lane whose credential is
            absent skips its live tests; that is a designed outcome, not a
            failure, so those names live here.
        settings_file: Whether the command RUNS the service and should
            therefore be pointed at this checkout's `.env` as the operator's
            settings file. A scope that runs the test suite leaves this off:
            the suite's environment is declared by the suite.
    """

    summary: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = field(default_factory=tuple)
    settings_file: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        """Every variable this scope admits, required first."""
        return (*self.required, *self.optional)


#: Provider credentials. Every one of these is OPTIONAL, because the test
#: suites that consume them already treat an absent credential as a skip with a
#: named reason (`src/vaultspec_a2a/conftest.py`'s prerequisite rule), and
#: escalate to a failure only when a caller guaranteed it with
#: `--require-prerequisite`. Making them required here would break exactly the
#: hosts that system was built to accommodate.
_PROVIDER_CREDENTIALS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "KIMI_MODEL_API_KEY",
    "KIMI_MODEL_BASE_URL",
    "KIMI_MODEL_CAPABILITIES",
    "KIMI_MODEL_MAX_CONTEXT_SIZE",
    "KIMI_MODEL_NAME",
    "ZAI_AUTH_TOKEN",
    "ZAI_API_KEY",
    "ZHIPU_API_KEY",
)

#: Observability. Optional everywhere: tracing that is not configured is off,
#: which is the correct behaviour for a developer machine.
_TELEMETRY: Final[tuple[str, ...]] = (
    "LANGSMITH_API_KEY",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_PROJECT",
    "LANGSMITH_TRACING",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_INSECURE",
)

#: The scopes, keyed by the name a recipe passes.
SCOPES: Final[dict[str, Scope]] = {
    "service": Scope(
        summary="Runs the gateway, worker, or product CLI against real providers.",
        # The internal token authenticates the gateway to the worker. A service
        # started without it does not degrade - it cannot accept the worker's
        # calls at all - so this is the one place a missing name is worth
        # stopping for.
        required=("VAULTSPEC_A2A_INTERNAL_TOKEN",),
        optional=(*_PROVIDER_CREDENTIALS, *_TELEMETRY),
        # The service reads every other setting out of the same file itself,
        # named below. Listing those names here instead would be a second copy
        # of the settings schema, kept by hand, in a module that cannot import
        # it to check itself.
        settings_file=True,
    ),
    "compose": Scope(
        summary="Runs development-only Jaeger and VidaiMock fixtures.",
        optional=(
            "JAEGER_OTLP_PORT",
            "JAEGER_UI_PORT",
            "VIDAIMOCK_PORT",
        ),
    ),
    "live-tests": Scope(
        summary="Runs test lanes whose prerequisites include provider credentials.",
        # Nothing is required: the suite's prerequisite rule turns an absent
        # credential into a skip that names what is missing and how to supply
        # it, and into a failure only when the caller declared it present with
        # `--require-prerequisite`. That is a better contract than this module
        # could impose, so it is left to do its job.
        #
        # No settings file: a suite that read a developer's `.env` as settings
        # would pass or fail differently on every machine, and the session's
        # own conftest is what declares the environment these tests run in.
        optional=(*_PROVIDER_CREDENTIALS, *_TELEMETRY),
    ),
}


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse `.env` into a mapping.

    A deliberately small parser: `KEY=VALUE` lines, `#` comments, optional
    `export ` prefix, and surrounding quotes stripped. It does not expand
    variables or interpret escapes, because the file it reads is a list of
    opaque secrets and interpreting one would be a way to corrupt it.

    Args:
        path: The environment file.

    Returns:
        The parsed mapping, empty when the file is absent or unreadable. Its
        VALUES are never logged; only its keys are ever named.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if not separator:
            continue
        name = name.strip()
        if not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        parsed[name] = value
    return parsed


def resolve(
    scope: Scope,
    base: dict[str, str],
    declared: dict[str, str],
    env_file: Path = ENV_FILE,
) -> dict[str, str]:
    """Build the child environment for one scope.

    Args:
        scope: The scope being granted.
        base: The environment this process inherited.
        declared: The parsed `.env` mapping.
        env_file: The file ``declared`` was parsed from, and the one a
            service-running scope names as the operator's settings file.

    Returns:
        A copy of ``base`` with the scope's names filled in from ``declared``
        where they are not already set, and - for a scope that runs the
        service - `VAULTSPEC_A2A_ENV_FILE` naming ``env_file``. An inherited
        value always wins, for the credential names and for the settings file
        alike: a caller who exported one for this command meant it, and `.env`
        silently overriding it would be the same class of surprise this whole
        change exists to remove. The file is named only when it exists, since
        the service refuses a named file that is not there rather than falling
        back to defaults.
    """
    child = dict(base)
    for name in scope.names:
        if (base.get(name) or "").strip():
            continue
        value = declared.get(name)
        if value:
            child[name] = value
    if (
        scope.settings_file
        and not (base.get(ENV_FILE_VARIABLE) or "").strip()
        and env_file.is_file()
    ):
        child[ENV_FILE_VARIABLE] = str(env_file)
    return child


def missing_required(scope: Scope, child: dict[str, str]) -> list[str]:
    """Return the scope's required variables that are not set.

    Args:
        scope: The scope being granted.
        child: The environment the command would run with.

    Returns:
        The absent NAMES, in declaration order. Never a value.
    """
    return [name for name in scope.required if not (child.get(name) or "").strip()]


def _report_missing(scope_name: str, scope: Scope, absent: list[str]) -> None:
    """Explain a missing-credential refusal on stderr, naming no values.

    Args:
        scope_name: The scope the caller asked for.
        scope: That scope.
        absent: The variables that are not set.
    """
    print(
        f"credentials: scope '{scope_name}' requires "
        f"{', '.join(absent)}, which {'is' if len(absent) == 1 else 'are'} not set.\n"
        f"  {scope.summary}\n"
        f"  Set them in {ENV_FILE.name} (see .env.example), or export them.\n"
        f"  Nothing was executed.",
        file=sys.stderr,
        flush=True,
    )


def describe(scope_name: str) -> int:
    """Report which of a scope's variables are present, by name and boolean.

    This is the ONLY inspection surface, and it exists so a person can answer
    "is my key loaded" without ever printing one.

    Args:
        scope_name: The scope to describe.

    Returns:
        :data:`OK`, or :data:`MISSING_CREDENTIAL` when a required variable is
        absent.
    """
    scope = SCOPES[scope_name]
    child = resolve(scope, dict(os.environ), read_env_file())
    print(f"scope '{scope_name}': {scope.summary}", flush=True)
    if scope.settings_file:
        named = child.get(ENV_FILE_VARIABLE)
        print(
            f"  {ENV_FILE_VARIABLE}: {named or 'unset'} (settings file)",
            flush=True,
        )
    for name in scope.names:
        present = bool((child.get(name) or "").strip())
        tier = "required" if name in scope.required else "optional"
        print(f"  {name}: {'set' if present else 'unset'} ({tier})", flush=True)
    return MISSING_CREDENTIAL if missing_required(scope, child) else OK


def run(scope_name: str, argv: list[str]) -> int:
    """Run a command with exactly one scope's variables.

    Args:
        scope_name: The scope to grant.
        argv: The command and its arguments.

    Returns:
        The command's own exit status, so every contract code in
        :mod:`dev.exit_codes` passes through unchanged;
        :data:`MISSING_CREDENTIAL` when a required variable is absent and the
        command was therefore never started; otherwise whatever
        :func:`dev.runner.run` reports, which is
        :data:`dev.exit_codes.TOOL_MISSING` when the executable is not on
        `PATH`.
    """
    scope = SCOPES[scope_name]
    child = resolve(scope, dict(os.environ), read_env_file())

    absent = missing_required(scope, child)
    if absent:
        _report_missing(scope_name, scope, absent)
        return MISSING_CREDENTIAL

    return runner.run(argv, child, cwd=REPO_ROOT, replace_env=True)


def main(argv: list[str] | None = None) -> int:
    """Grant one scope and run a command, or describe a scope.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The command's exit status, or the description's.
    """
    # `--describe` is lifted out before parsing because the command that
    # follows the scope is captured with REMAINDER, which swallows any flag
    # after the positional - including this one. Pulling it out first makes
    # `credentials service --describe` mean what it reads as.
    raw = list(sys.argv[1:] if argv is None else argv)
    describing = "--describe" in raw
    raw = [item for item in raw if item != "--describe"]

    parser = argparse.ArgumentParser(
        prog="python -m dev.credentials",
        description="Run a command with exactly the credentials its scope declares.",
    )
    parser.add_argument("scope", choices=sorted(SCOPES))
    parser.add_argument(
        "--describe",
        action="store_true",
        help="report which of the scope's variables are set, by name; never a value",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(raw)

    if describing:
        return describe(args.scope)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no command given; pass it after `--`, or use --describe")
    return run(args.scope, command)


if __name__ == "__main__":
    sys.exit(main())
