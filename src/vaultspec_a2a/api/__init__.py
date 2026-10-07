"""Expose the public Hypertext Transfer Protocol API schemas.

API means application programming interface throughout this package.

This package exports the wire types defined by
:mod:`vaultspec_a2a.api.schemas`. It doesn't own application orchestration or
the event relay.

Build the application with :func:`vaultspec_a2a.api.app.create_app`.
:class:`vaultspec_a2a.streaming.RelayHub` owns the gateway's event relay, its
subscribers and the live run-state mirror.

Request handling delegates orchestration to direct
:mod:`vaultspec_a2a.control` service modules. The generated OpenAPI document
at ``/openapi.json`` is authoritative for the served edge surface.
"""

from .schemas import ThreadStateSnapshot as ThreadStateSnapshot

__all__ = [
    "ThreadStateSnapshot",
]
