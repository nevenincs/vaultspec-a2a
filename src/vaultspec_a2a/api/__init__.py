"""Hold the public Hypertext Transfer Protocol API edge.

API means application programming interface throughout this package.

The wire types live in :mod:`vaultspec_a2a.api.schemas`, imported from the
module that declares each one; this package root re-exports nothing. It doesn't
own application orchestration or the event relay.

Build the application with :func:`vaultspec_a2a.api.app.create_app`.
:class:`vaultspec_a2a.streaming.subscribers.RelayHub` owns the gateway's event
relay, its subscribers and the live run-state mirror.

Request handling delegates orchestration to direct
:mod:`vaultspec_a2a.control` service modules. The generated OpenAPI document
at ``/openapi.json`` is authoritative for the served edge surface.
"""

__all__: list[str] = []
