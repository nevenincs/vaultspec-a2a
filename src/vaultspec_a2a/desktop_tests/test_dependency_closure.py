"""Certify the installed desktop dependency boundary from production artifacts.

The gate builds the real wheel, exports the locked base/server/RAG closures, and
installs only the base closure into a clean interpreter.  Production gateway and
worker telemetry are then imported by independent child interpreters.  No probe
module from the installed package's test tree is used, so excluding packaged tests
cannot remove this gate's production coverage.

The server dry run certifies the interpreter's native target; the RAG dry run uses
the supported CPython 3.13 x86-64 Windows target.  Cross-target RAG support remains
bounded by the limitations recorded by W01.P01.S02; in particular, this test does
not claim generic manylinux 2.28 or Intel/older macOS Torch support.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Final, cast

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_DISTRIBUTION_NAME: Final = "vaultspec-a2a"
_EXTRAS: Final = frozenset({"rag", "server"})
_RAG_ROOTS: Final = frozenset({"torch", "vaultspec-rag"})
_SERVER_ROOTS: Final = frozenset(
    {
        "asyncpg",
        "langgraph-checkpoint-postgres",
        "opentelemetry-exporter-otlp-proto-grpc",
        "psycopg",
    }
)

_DISTRIBUTION_REPORT = r"""
import importlib.metadata
import json

import vaultspec_a2a

distribution = importlib.metadata.distribution("vaultspec-a2a")
installed = sorted(
    {
        name
        for item in importlib.metadata.distributions()
        if (name := item.metadata["Name"]) is not None
    }
)
print(
    json.dumps(
        {
            "installed": installed,
            "module_file": vaultspec_a2a.__file__,
            "provides_extra": distribution.metadata.get_all("Provides-Extra") or [],
            "requires_dist": distribution.requires or [],
            "version": distribution.version,
        },
        sort_keys=True,
    )
)
"""

_TELEMETRY_REPORT = r"""
import importlib.util
import json
import sys

profile = sys.argv[1]
if profile == "gateway":
    from vaultspec_a2a.api.app import configure_telemetry

    service_name = None
elif profile == "worker":
    from vaultspec_a2a.worker.app import configure_telemetry

    service_name = "vaultspec-worker"
else:
    raise ValueError(f"unknown telemetry profile: {profile}")

config = configure_telemetry(service_name=service_name)
print(
    json.dumps(
        {
            "exporter_present": importlib.util.find_spec(
                "opentelemetry.exporter"
            )
            is not None,
            "otlp_available": config.otlp_available,
            "profile": profile,
            "sdk_available": config.sdk_available,
            "sdk_enabled": config.sdk_enabled,
            "service_name": config.service_name,
        },
        sort_keys=True,
    )
)
"""


@dataclass(frozen=True)
class DistributionMetadata:
    """The fields relevant to dependency partitioning."""

    extras: frozenset[str]
    requirements: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class ClosureEvidence:
    """Production-artifact evidence shared by the assertions in this module."""

    environment: Path
    installed_report: dict[str, object]
    metadata: DistributionMetadata
    pylock_names: dict[str, frozenset[str]]
    telemetry_reports: dict[str, dict[str, object]]


def _normalize_name(name: str) -> str:
    return str(canonicalize_name(name))


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise AssertionError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "LANGSMITH_TRACING",
        "OTEL_EXPORTER_CONSOLE",
        "OTEL_SDK_DISABLED",
        "OTEL_SERVICE_NAME",
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["UV_NO_PROGRESS"] = "1"
    return environment


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _read_pylock_names(path: Path) -> frozenset[str]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = cast("list[dict[str, object]]", document["packages"])
    return frozenset(
        _normalize_name(cast("str", package["name"])) for package in packages
    )


def _read_wheel_metadata(wheel: Path) -> DistributionMetadata:
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_files) == 1, metadata_files
        message = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_files[0])
        )

    return DistributionMetadata(
        extras=frozenset(message.get_all("Provides-Extra", [])),
        requirements=tuple(message.get_all("Requires-Dist", [])),
        version=cast("str", message["Version"]),
    )


def _requirement_groups(
    requirements: tuple[str, ...],
    extras: frozenset[str],
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    unconditional: set[str] = set()
    optional: dict[str, set[str]] = {extra: set() for extra in extras}
    for requirement_text in requirements:
        requirement = Requirement(requirement_text)
        name = _normalize_name(requirement.name)
        marker = requirement.marker
        if marker is None or marker.evaluate({"extra": ""}):
            unconditional.add(name)
            continue
        for extra in extras:
            if marker.evaluate({"extra": extra}):
                optional[extra].add(name)

    return frozenset(unconditional), {
        extra: frozenset(names) for extra, names in optional.items()
    }


def _json_report(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = result.stdout.strip().splitlines()
    assert lines, result
    report = json.loads(lines[-1])
    assert isinstance(report, dict), report
    return cast("dict[str, object]", report)


def _string_list(report: dict[str, object], key: str) -> tuple[str, ...]:
    value = report[key]
    assert isinstance(value, list), value
    assert all(isinstance(item, str) for item in value), value
    return tuple(cast("list[str]", value))


@pytest.fixture(scope="module")
def closure_evidence(tmp_path_factory: pytest.TempPathFactory) -> ClosureEvidence:
    """Build, resolve, install, and exercise the production distribution."""
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to certify the locked distribution"

    sandbox = tmp_path_factory.mktemp("desktop-dependency-closure")
    distribution_dir = sandbox / "dist"
    distribution_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_dir), "--no-sources"],
        cwd=_PROJECT_ROOT,
    )
    wheels = list(distribution_dir.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]
    metadata = _read_wheel_metadata(wheel)

    pylocks: dict[str, Path] = {}
    for profile in ("base", "server", "rag"):
        pylock = sandbox / f"pylock.{profile}.toml"
        command = [
            uv,
            "export",
            "--format",
            "pylock.toml",
            "--locked",
            "--no-dev",
            "--no-emit-project",
        ]
        if profile != "base":
            command.extend(["--extra", profile])
        command.extend(["--output-file", str(pylock)])
        _run(command, cwd=_PROJECT_ROOT)
        pylocks[profile] = pylock

    environment = sandbox / "venv"
    _run(
        [uv, "venv", "--python", sys.executable, str(environment)],
        cwd=sandbox,
    )
    python = _environment_python(environment)
    assert python.is_file(), python

    for profile in ("server", "rag"):
        command = [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--dry-run",
        ]
        if profile == "rag":
            command.extend(
                [
                    "--python-platform",
                    "x86_64-pc-windows-msvc",
                    "--python-version",
                    "3.13",
                ]
            )
        command.extend(["-r", str(pylocks[profile])])
        _run(command, cwd=sandbox)

    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(pylocks["base"]),
        ],
        cwd=sandbox,
    )
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        cwd=sandbox,
    )
    _run([uv, "pip", "check", "--python", str(python)], cwd=sandbox)

    installed_report = _json_report(
        _run([str(python), "-I", "-c", _DISTRIBUTION_REPORT], cwd=sandbox)
    )
    telemetry_reports = {
        profile: _json_report(
            _run(
                [str(python), "-I", "-c", _TELEMETRY_REPORT, profile],
                cwd=sandbox,
            )
        )
        for profile in ("gateway", "worker")
    }

    return ClosureEvidence(
        environment=environment,
        installed_report=installed_report,
        metadata=metadata,
        pylock_names={
            profile: _read_pylock_names(path) for profile, path in pylocks.items()
        },
        telemetry_reports=telemetry_reports,
    )


def test_installed_metadata_preserves_distinct_optional_profiles(
    closure_evidence: ClosureEvidence,
) -> None:
    """The installed wheel keeps heavy and service roots conditional."""
    metadata = closure_evidence.metadata
    installed = closure_evidence.installed_report
    installed_metadata = DistributionMetadata(
        extras=frozenset(_string_list(installed, "provides_extra")),
        requirements=_string_list(installed, "requires_dist"),
        version=cast("str", installed["version"]),
    )
    assert installed_metadata == metadata
    assert metadata.extras == _EXTRAS

    base_roots, optional_roots = _requirement_groups(
        metadata.requirements, metadata.extras
    )
    assert optional_roots["rag"] == _RAG_ROOTS
    assert optional_roots["server"] == _SERVER_ROOTS
    assert _RAG_ROOTS.isdisjoint(base_roots)
    assert optional_roots["server"].isdisjoint(optional_roots["rag"])


def test_locked_optional_closures_resolve_without_cross_contamination(
    closure_evidence: ClosureEvidence,
) -> None:
    """Canonical locked uv exports keep server and RAG profiles independent."""
    base_roots, optional_roots = _requirement_groups(
        closure_evidence.metadata.requirements, closure_evidence.metadata.extras
    )
    base = closure_evidence.pylock_names["base"]
    server = closure_evidence.pylock_names["server"]
    rag = closure_evidence.pylock_names["rag"]

    assert base_roots <= base
    assert base <= server
    assert base <= rag
    assert optional_roots["server"] <= server
    assert optional_roots["server"].isdisjoint(base)
    assert optional_roots["server"].isdisjoint(rag)
    assert optional_roots["rag"] <= rag
    assert optional_roots["rag"].isdisjoint(base)
    assert optional_roots["rag"].isdisjoint(server)


def test_clean_base_install_uses_only_production_desktop_dependencies(
    closure_evidence: ClosureEvidence,
) -> None:
    """The installed base distribution contains neither optional profile."""
    report = closure_evidence.installed_report
    installed = frozenset(
        _normalize_name(name) for name in _string_list(report, "installed")
    )
    base = closure_evidence.pylock_names["base"]
    server = closure_evidence.pylock_names["server"]
    rag = closure_evidence.pylock_names["rag"]
    optional_only = (server | rag) - base
    module_file = Path(cast("str", report["module_file"])).resolve()

    assert _DISTRIBUTION_NAME in installed
    assert optional_only.isdisjoint(installed)
    assert module_file.is_relative_to(closure_evidence.environment.resolve())
    assert not module_file.is_relative_to(_PROJECT_ROOT)


@pytest.mark.parametrize(
    ("profile", "service_name"),
    (("gateway", "vaultspec-a2a"), ("worker", "vaultspec-worker")),
)
def test_clean_base_initializes_production_telemetry_without_otlp(
    closure_evidence: ClosureEvidence,
    profile: str,
    service_name: str,
) -> None:
    """Gateway and worker production imports retain base-only telemetry."""
    report = closure_evidence.telemetry_reports[profile]
    assert report == {
        "exporter_present": False,
        "otlp_available": False,
        "profile": profile,
        "sdk_available": True,
        "sdk_enabled": True,
        "service_name": service_name,
    }
