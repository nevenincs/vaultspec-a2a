"""Prove gateway and worker telemetry start in a base-only installation.

Run this module with the Python interpreter from a clean installation of the
default project dependencies. The probe rejects environments that contain the
optional ``opentelemetry.exporter`` namespace, then exercises each production
telemetry initialization entrypoint in its own process.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from typing import Any


def _initialize_profile(profile: str) -> dict[str, Any]:
    if importlib.util.find_spec("opentelemetry.exporter") is not None:
        raise RuntimeError(
            "clean-base probe requires opentelemetry.exporter to be absent"
        )

    if profile == "gateway":
        from vaultspec_a2a.api.app import configure_telemetry

        service_name = None
    else:
        from vaultspec_a2a.worker.app import configure_telemetry

        service_name = "vaultspec-worker"
    config = configure_telemetry(service_name=service_name)
    expected_service = "vaultspec-a2a" if profile == "gateway" else service_name

    if not config.sdk_available or not config.sdk_enabled:
        raise RuntimeError(f"{profile} did not initialize the mandatory OTel SDK")
    if config.otlp_available:
        raise RuntimeError(f"{profile} incorrectly reported OTLP as available")
    if config.service_name != expected_service:
        raise RuntimeError(
            f"{profile} configured {config.service_name!r}, expected "
            f"{expected_service!r}"
        )

    return {
        "profile": profile,
        "sdk_available": config.sdk_available,
        "sdk_enabled": config.sdk_enabled,
        "otlp_available": config.otlp_available,
        "service_name": config.service_name,
    }


def _run_profile(profile: str) -> dict[str, Any]:
    env = dict(os.environ)
    for key in (
        "LANGSMITH_TRACING",
        "OTEL_EXPORTER_CONSOLE",
        "OTEL_SDK_DISABLED",
        "OTEL_SERVICE_NAME",
        "PYTHONHOME",
        "PYTHONPATH",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.telemetry.tests.probe_clean_base",
            "--profile",
            profile,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{profile} telemetry process failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("gateway", "worker"))
    args = parser.parse_args()

    if args.profile is not None:
        print(json.dumps(_initialize_profile(args.profile), sort_keys=True))
        return

    reports = [_run_profile("gateway"), _run_profile("worker")]
    print(json.dumps({"status": "ok", "reports": reports}, sort_keys=True))


if __name__ == "__main__":
    main()
