"""Select the first healthy real provider probe for certifying live suites.

This module deliberately runs the existing real provider probes rather than
reimplementing probe logic. It exits 0 and prints the selected provider name
when any candidate passes. It exits 1 with a failure summary when none do.
"""

from __future__ import annotations

import subprocess
import sys


__all__ = ["main"]


_PROBE_ORDER: tuple[str, ...] = ("claude", "openai", "gemini", "zhipu")
_PROBE_TIMEOUT_SECONDS: dict[str, int] = {
    "claude": 180,
    "openai": 90,
    "gemini": 180,
    "zhipu": 90,
}
_INTERACTIVE_AUTH_PROVIDERS = frozenset({"claude", "gemini"})


def _probe_timeout_seconds(provider: str) -> int | None:
    """Return the outer subprocess watchdog for the probe wrapper.

    Interactive ACP providers already enforce their own per-step watchdogs,
    including a dedicated browser-auth backstop. Do not let this outer wrapper
    cut them off before the probe itself resolves success, rejection, or auth
    cancellation.
    """
    if provider in _INTERACTIVE_AUTH_PROVIDERS:
        return None
    return _PROBE_TIMEOUT_SECONDS[provider]


def _run_probe(provider: str) -> subprocess.CompletedProcess[str]:
    timeout = _probe_timeout_seconds(provider)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            f"vaultspec_a2a.providers.probes.{provider}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    """Print and return the first healthy real provider for certifying suites."""
    failures: list[str] = []

    for provider in _PROBE_ORDER:
        try:
            result = _run_probe(provider)
        except subprocess.TimeoutExpired:
            timeout = _probe_timeout_seconds(provider)
            timeout_label = (
                "interactive watchdog" if timeout is None else f"{timeout}s"
            )
            failures.append(
                f"{provider}: probe subprocess exceeded {timeout_label}"
            )
            continue

        detail = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            sys.stdout.write(f"{provider}\n")
            return 0

        tail = detail[-600:] if detail else "probe failed without output"
        failures.append(f"{provider}: {tail}")

    sys.stderr.write("No certifying live provider probe passed.\n")
    for failure in failures:
        sys.stderr.write(f"- {failure}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
