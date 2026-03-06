"""ACP agent probes for manual verification of the protocol lifecycle.

Each probe runs the full ACP handshake (``initialize`` -> ``session/new`` ->
``session/prompt``) against a real agent subprocess and reports pass/fail via
both structured logging and process exit code.

Usage::

    python -m vaultspec_a2a.providers.probes.claude   # ACP subprocess
    python -m vaultspec_a2a.providers.probes.gemini   # ACP subprocess
    python -m vaultspec_a2a.providers.probes.openai   # HTTP API
    python -m vaultspec_a2a.providers.probes.zhipu    # HTTP API (GLM)

Public API
----------
:class:`ProbeResult` and :func:`run_probe` are the package-level primitives.
Provider-specific entry-points (``claude.main``, ``gemini.main``) are imported
directly from their modules to avoid the Python ``__main__`` re-import warning.
"""

from ._http import run_http_probe
from ._protocol import ProbeResult, run_probe


__all__ = [
    "ProbeResult",
    "run_http_probe",
    "run_probe",
]
