"""Health check endpoint and heartbeat emitter for the worker process."""

__all__ = ["HealthCheck"]


class HealthCheck:
    """Periodic heartbeat emitter and /healthz endpoint handler."""
