"""Frontend-backend wire contract schema models.

Each model is imported from the module that declares it (``schemas.gateway``,
``schemas.provider_catalog``); this package root re-exports nothing.

The run read model is not declared here. Run-history serves the Layer-1
dataclass ``vaultspec_a2a.thread.snapshots.ThreadStateSnapshot`` directly, so the
snapshot has one declaration rather than a wire mirror. Domain types a wire
model merely carries as field types, ``PlanEntry`` among them, belong to their
own modules and are never given a second home here.
"""

__all__: list[str] = []
