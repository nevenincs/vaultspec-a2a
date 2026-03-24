"""Shared LangSmith trace query helper for Layer 2 runner scripts.

After a graph run completes, call `print_trace_summary(thread_id)` to
fetch and display the node sequence, latency, and any errors from the
most recent LangSmith trace for that thread.

Requires LANGSMITH_API_KEY and LANGSMITH_TRACING=true in the environment.
If tracing is disabled or the client is unavailable, prints a warning and
returns gracefully.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

_logger = logging.getLogger(__name__)


def _trace_print(msg: str) -> None:
    """Write trace output to both logger and stdout for CLI visibility."""
    _logger.info(msg)
    print(msg)


def print_trace_summary(thread_id: str, project_name: str | None = None) -> None:
    """Query LangSmith for the most recent trace for thread_id and print a summary.

    Polls briefly to allow the trace to propagate after the run completes,
    then lists all child runs (nodes) in start-time order, printing:
      - node name, run type, status
      - latency in ms
      - input/output token counts if available
      - error message if the run errored

    Args:
        thread_id:    The LangGraph thread_id used as configurable["thread_id"].
        project_name: LangSmith project name. Defaults to settings.langsmith_project,
                      then "default".
    """
    from ..control.config import settings

    if not settings.langsmith_api_key:
        _trace_print("[trace] LANGSMITH_API_KEY not set — skipping trace query.")
        return
    if not settings.langsmith_tracing:
        _trace_print("[trace] LangSmith tracing not enabled — skipping trace query.")
        return

    try:
        from langsmith import Client
    except ImportError:
        _trace_print("[trace] langsmith package not installed — skipping trace query.")
        return

    resolved_project = project_name or settings.langsmith_project or "default"

    client = Client(
        api_url=settings.langsmith_endpoint or None,
    )

    # Allow up to 10s for the trace to propagate to LangSmith.
    _trace_print(
        f"\n[trace] Querying LangSmith project={resolved_project!r}"
        f" thread_id={thread_id!r} ..."
    )
    root_run = None
    for attempt in range(5):
        try:
            runs = list(
                client.list_runs(
                    project_name=resolved_project,
                    filter=(
                        'eq(metadata_key, "thread_id")'
                        f' and eq(metadata_value, "{thread_id}")'
                    ),
                    run_type="chain",
                    limit=1,
                )
            )
        except Exception:
            # Older SDK versions don't support metadata filter — fall back.
            _logger.debug(
                "[trace] metadata filter unsupported; falling back to scan",
                exc_info=True,
            )
            runs = []

        if not runs:
            # Fallback: list recent root runs and match by thread_id in metadata
            try:
                recent = list(
                    client.list_runs(
                        project_name=resolved_project,
                        run_type="chain",
                        limit=20,
                        is_root=True,
                    )
                )
                for r in recent:
                    meta = r.extra.get("metadata", {}) if r.extra else {}
                    if meta.get("thread_id") == thread_id:
                        runs = [r]
                        break
            except Exception:
                _logger.debug(
                    "[trace] fallback run scan failed for thread_id=%s",
                    thread_id,
                    exc_info=True,
                )

        if runs:
            root_run = runs[0]
            break

        if attempt < 4:
            time.sleep(2)

    if root_run is None:
        return

    root_latency_ms: float | None = None
    if root_run.start_time and root_run.end_time:
        root_latency_ms = (
            root_run.end_time - root_run.start_time
        ).total_seconds() * 1000
    header = f"[trace] root run id={root_run.id} status={root_run.status}"
    if root_latency_ms is not None:
        header += f" total_latency={root_latency_ms:.0f}ms"
    _trace_print(header)

    # Fetch all child runs (nodes) under the root trace.
    try:
        child_runs = sorted(
            client.list_runs(
                project_name=resolved_project, trace_id=root_run.id, limit=100
            ),
            key=lambda r: r.start_time or datetime.min.replace(tzinfo=UTC),
        )
    except Exception:
        _logger.debug(
            "[trace] failed to fetch child runs for trace %s",
            root_run.id,
            exc_info=True,
        )
        return

    for run in child_runs:
        latency_ms = None
        if run.start_time and run.end_time:
            latency_ms = (run.end_time - run.start_time).total_seconds() * 1000

        tokens_in = None
        tokens_out = None
        if run.prompt_tokens is not None:
            tokens_in = run.prompt_tokens
        if run.completion_tokens is not None:
            tokens_out = run.completion_tokens

        parts = [f"  [{run.run_type}] {run.name!r}  status={run.status}"]
        if latency_ms is not None:
            parts.append(f"latency={latency_ms:.0f}ms")
        if tokens_in is not None or tokens_out is not None:
            parts.append(f"tokens(in={tokens_in} out={tokens_out})")
        if run.error:
            parts.append(f"ERROR={run.error[:120]!r}")
        _trace_print("  ".join(parts))

    # Summarise errors
    errors = [r for r in child_runs if r.error]
    if errors:
        _trace_print(f"[trace] {len(errors)} node(s) errored:")
        for r in errors:
            _trace_print(f"  {r.name!r}: {str(r.error)[:200]}")
    else:
        _trace_print("[trace] no errors")
