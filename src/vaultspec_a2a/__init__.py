"""Provide the root package for the Vaultspec agent-to-agent (A2A) distribution.

Configuration lives in :mod:`vaultspec_a2a.domain_config`.

Package surfaces include :mod:`vaultspec_a2a.api`,
:mod:`vaultspec_a2a.authoring`, :mod:`vaultspec_a2a.cli`,
:mod:`vaultspec_a2a.context`, :mod:`vaultspec_a2a.control`,
:mod:`vaultspec_a2a.database`, :mod:`vaultspec_a2a.graph`,
:mod:`vaultspec_a2a.ipc`, :mod:`vaultspec_a2a.lifecycle`,
:mod:`vaultspec_a2a.protocols`, :mod:`vaultspec_a2a.providers`,
:mod:`vaultspec_a2a.streaming`, :mod:`vaultspec_a2a.team`,
:mod:`vaultspec_a2a.telemetry`, :mod:`vaultspec_a2a.thread`,
:mod:`vaultspec_a2a.utils`, :mod:`vaultspec_a2a.worker`, and
:mod:`vaultspec_a2a.workspace`.

Import features from their owning modules. The root package doesn't re-export
those public APIs.
"""
