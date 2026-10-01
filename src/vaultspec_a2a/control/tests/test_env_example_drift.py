"""The example and the code agree on every name, every value, in both directions.

The coverage tests beside this one hold the example's NAMES to the settings
classes. Names agreeing is not enough for an operator who copies the file:

* a setting nothing reads is a knob that turns nothing, and the example then
  documents it as though it did;
* a value the example shows can drift from the code's default, so a copied file
  silently changes behaviour - an example once bound the gateway to every
  interface while the code bound loopback;
* a line can fail to load at all, and the operator finds out at startup;
* a name spelled in the code, a Compose file or the docs can name a variable no
  settings class declares, so setting it does nothing.

Values are judged by the service's own loader rather than by parsing them here:
each profile an operator can copy is written to a dotenv file and loaded by the
settings class in a child process whose environment sets nothing, so every
decoder and cross-field validator applies exactly as it does at startup.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, cast

import pytest

from ...control.config import Settings
from ._env_example import (
    DOCUMENTED_BUT_NOT_READ,
    INTEGRATION_EXAMPLE,
    REPO_ROOT,
    Assignment,
    assignments,
    declared_names,
    documented,
    harness_section,
    service_section,
    setting_field_by_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: Lines whose value deliberately differs from the code's default, each with
#: why. Every other line must show the default, so a changed default and a
#: stale example cannot pass each other silently.
_DOCUMENTED_OVERRIDES = {
    "VAULTSPEC_A2A_DATABASE_URL": "a relocated SQLite store, and the Postgres profile",
    "VAULTSPEC_A2A_DATABASE_BACKEND": "the Postgres profile",
    "VAULTSPEC_A2A_CHECKPOINT_BACKEND": "the Postgres profile",
    "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL": "the Postgres profile",
    "VAULTSPEC_A2A_PROVIDER_IDENTITY_LAUNCHER": "the Compose worker image's value",
    "VAULTSPEC_A2A_PROVIDER_AGENT_UID": "the Compose worker image's value",
    "VAULTSPEC_A2A_PROVIDER_AGENT_GID": "the Compose worker image's value",
    "VAULTSPEC_A2A_INSTALL_ROOT": "the container image's install root",
    "VAULTSPEC_A2A_MOCK_API_BASE": "the integration profile's VidaiMock address",
    "VAULTSPEC_A2A_ENGINE_SERVE_CMD": "unset, the launcher runs this same template",
    "OTEL_SERVICE_VERSION": "a sample service identity",
    "OTEL_SDK_DISABLED": "an opt-in switch shown switched on",
    "OTEL_EXPORTER_CONSOLE": "an opt-in switch shown switched on",
    "OTEL_TRACES_EXPORTER": "an opt-in 'none' that builds no exporter",
    "OTEL_METRICS_EXPORTER": "an opt-in 'none' that builds no reader",
    "CI": "an opt-in switch shown switched on",
    "NO_COLOR": "an opt-in switch shown switched on",
}

#: Where a setting can be read: shipped code, the container entrypoints, and
#: the repository tooling. Tests are excluded, because a setting only a test
#: reads is still one the product ignores.
_READER_ROOTS = ("src/vaultspec_a2a", "service", "dev")

#: Where an environment name can be spelled for an operator or a process to
#: act on: the readers above, plus Compose, images, workflows and docs.
_SPELLER_ROOTS = (*_READER_ROOTS, "docs", ".github", "scripts")
_SPELLER_FILES = (
    "justfile",
    "README.md",
    "CONTRIBUTING.md",
    ".env.integration.example",
)
_NOT_SHIPPED = frozenset({"tests", "service_tests", "__pycache__", "node_modules"})

_SERVICE_NAME = re.compile(r"\bVAULTSPEC_A2A_[A-Z0-9_]*")
_HARNESS_NAME = re.compile(r"\bVAULTSPEC_[A-Z0-9_]+\b")


def _shipped(path: Path) -> bool:
    return not (
        _NOT_SHIPPED.intersection(path.relative_to(REPO_ROOT).parts)
        or path.name.startswith("test_")
        or path.name == "conftest.py"
    )


def _shipped_files(roots: tuple[str, ...], pattern: str) -> Iterator[Path]:
    for root in roots:
        directory = REPO_ROOT / root
        if directory.is_dir():
            yield from (
                path
                for path in sorted(directory.rglob(pattern))
                if path.is_file() and _shipped(path)
            )


def _names_read_by_the_code() -> set[str]:
    """Every attribute and string the shipped code reads a setting through.

    An attribute access covers ``settings.port``; a string covers a setting
    named by field, as an entrypoint does with an env-name helper. A string in
    a decorator is not a read: a validator naming its own field is the field's
    declaration talking to itself, and it once kept two dead settings alive.
    """
    read: set[str] = set()
    for path in _shipped_files(_READER_ROOTS, "*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        in_decorators = {
            id(node)
            for owner in ast.walk(tree)
            if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            for decorator in owner.decorator_list
            for node in ast.walk(decorator)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                read.add(node.attr)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in in_decorators
            ):
                read.add(node.value)
    return read


def test_every_setting_is_read_by_the_code() -> None:
    """A declared setting nothing reads is a knob that turns nothing."""
    read = _names_read_by_the_code()
    unread = sorted(field for field in Settings.model_fields if field not in read)

    assert not unread, (
        f"settings no shipped code reads: {unread}. Remove each, or wire the "
        "behaviour it claims to configure."
    )


def _commented_blocks(lines: list[Assignment]) -> list[list[Assignment]]:
    """Group commented lines into the runs an operator uncomments together."""
    blocks: list[list[Assignment]] = []
    for line in (line for line in lines if line.commented):
        if blocks and blocks[-1][-1].line == line.line - 1:
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _profiles() -> list[list[Assignment]]:
    """Every profile an operator can copy: the file as is, then each block.

    The uncommented lines are what a copied file sets. Each run of adjacent
    commented lines is a block an operator uncomments together, loaded on top
    of the uncommented lines it would sit beside - the way the Postgres block
    replaces the SQLite backends.
    """
    settings_names = setting_field_by_name()
    lines = [
        line for line in assignments(service_section()) if line.name in settings_names
    ]
    active = [line for line in lines if not line.commented]
    return [active, *[[*active, *block] for block in _commented_blocks(lines)]]


def _load_profiles(
    profiles: list[list[tuple[str, str]]], workdir: Path
) -> list[dict[str, object]]:
    """Load *profiles* in a child whose environment sets no setting at all."""
    unset = declared_names()
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in unset and not name.startswith("VAULTSPEC_")
    }
    completed = subprocess.run(
        [sys.executable, "-m", "vaultspec_a2a.control.tests._example_profile_loader"],
        input=json.dumps({"profiles": profiles}),
        cwd=str(workdir),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def loaded_profiles(
    tmp_path_factory: pytest.TempPathFactory,
) -> list[tuple[list[Assignment], dict[str, object]]]:
    profiles = _profiles()
    results = _load_profiles(
        [[(line.name, line.value) for line in profile] for profile in profiles],
        tmp_path_factory.mktemp("env-example"),
    )
    return list(zip(profiles, results, strict=True))


def _departures(
    loaded_profiles: list[tuple[list[Assignment], dict[str, object]]],
) -> dict[str, set[int]]:
    """Each name whose shown value is not the default, with its lines."""
    departures: dict[str, set[int]] = defaultdict(set)
    for profile, result in loaded_profiles:
        if result["error"] is not None:
            # Reported by the load test; a profile that never loaded has no
            # values to compare.
            continue
        reports = cast("list[dict[str, object]]", result["lines"])
        for line, report in zip(profile, reports, strict=True):
            if line.value and not report["matches_default"]:
                departures[line.name].add(line.line)
    return departures


def test_every_profile_an_operator_can_copy_loads(
    loaded_profiles: list[tuple[list[Assignment], dict[str, object]]],
) -> None:
    """A line that fails to load is found here, not at an operator's startup."""
    failures = [
        (sorted({line.line for line in profile if line.commented}), result["error"])
        for profile, result in loaded_profiles
        if result["error"] is not None
    ]

    assert len(loaded_profiles) > 1, "the example has no commented block to load"
    assert not failures, f"profiles that fail to load (block lines, error): {failures}"


def test_every_value_shown_is_the_code_default(
    loaded_profiles: list[tuple[list[Assignment], dict[str, object]]],
) -> None:
    """A shown value that is not the default must say it is a departure."""
    drifted = {
        name: sorted(lines)
        for name, lines in _departures(loaded_profiles).items()
        if name not in _DOCUMENTED_OVERRIDES
    }

    assert not drifted, (
        f"example values that differ from the code default: {drifted}. Show the "
        "default, or record why the example departs from it."
    )


def test_every_recorded_departure_still_departs(
    loaded_profiles: list[tuple[list[Assignment], dict[str, object]]],
) -> None:
    """A stale departure would excuse the next real drift on that line."""
    departing = set(_departures(loaded_profiles))

    stale = sorted(set(_DOCUMENTED_OVERRIDES) - departing)

    assert not stale, f"recorded departures whose value is now the default: {stale}"


def test_a_name_is_assigned_twice_only_as_an_alternative() -> None:
    """A repeated line must offer a different value, in a different profile.

    The same value twice is redundant, and two values in one block contradict
    each other: whichever the loader reads last silently wins.
    """
    every_line = assignments(service_section())
    # The copied file is one profile; each commented block is another.
    profile_of = {line.line: -1 for line in every_line if not line.commented}
    for index, block in enumerate(_commented_blocks(every_line)):
        profile_of.update({line.line: index for line in block})
    by_name: dict[str, list[Assignment]] = defaultdict(list)
    for line in every_line:
        by_name[line.name].append(line)
    problems: dict[str, str] = {}
    for name, lines in by_name.items():
        numbers = [line.line for line in lines]
        if len({line.value for line in lines}) < len(lines):
            problems[name] = f"repeats a value on lines {numbers}"
        elif len({profile_of[number] for number in numbers}) < len(lines):
            problems[name] = f"is set twice in one profile on lines {numbers}"

    assert not problems, problems


def test_every_assignment_names_a_setting_or_its_owner() -> None:
    """Every line an operator can set names something that will read it."""
    readable = set(setting_field_by_name()) | set(DOCUMENTED_BUT_NOT_READ)
    unowned = sorted({line.name for line in assignments(service_section())} - readable)

    assert not unowned, f"example lines nothing reads: {unowned}"


def test_every_name_the_code_spells_is_declared() -> None:
    """A service name in code, Compose, images or docs must be one a class reads.

    The harness's own names are held to the harness by its section of the
    example and ``dev/tests/test_harness_env_names.py``, so a name documented
    there counts as declared here.
    """
    known = declared_names() | set(_HARNESS_NAME.findall(harness_section()))
    spelled: dict[str, set[str]] = defaultdict(set)
    files = [
        *_shipped_files(_SPELLER_ROOTS, "*"),
        *(REPO_ROOT / name for name in _SPELLER_FILES if (REPO_ROOT / name).is_file()),
    ]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name in _SERVICE_NAME.findall(text):
            if name in known:
                continue
            # A prefix spelled on its own names a family, not a variable.
            if name.endswith("_") and any(other.startswith(name) for other in known):
                continue
            spelled[name].add(str(path.relative_to(REPO_ROOT)))

    assert not spelled, {name: sorted(paths) for name, paths in spelled.items()}


def test_the_documented_owners_are_named_in_the_file() -> None:
    """An owner recorded for a name the file no longer mentions is stale."""
    text = documented()

    stale = sorted(name for name in DOCUMENTED_BUT_NOT_READ if name not in text)

    assert not stale, f"recorded owners for names the example no longer has: {stale}"


def test_the_integration_example_loads(tmp_path: Path) -> None:
    """The integration profile, uncommented whole, is a profile that loads."""
    profile = [
        (line.name, line.value) for line in assignments(documented(INTEGRATION_EXAMPLE))
    ]

    [result] = _load_profiles([profile], tmp_path)

    assert profile, "the integration example sets nothing"
    assert result["error"] is None, result["error"]
