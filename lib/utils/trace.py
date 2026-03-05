"""Shared LangSmith trace query helper for Layer 2 runner scripts.

After a graph run completes, call `print_trace_summary(thread_id)` to
fetch and display the node sequence, latency, and any errors from the
most recent LangSmith trace for that thread.

Requires LANGSMITH_API_KEY and LANGSMITH_TRACING=true in the environment.
If tracing is disabled or the client is unavailable, prints a warning and
returns gracefully.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone


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
        project_name: LangSmith project name. Defaults to LANGSMITH_PROJECT env
                      var, then LANGCHAIN_PROJECT, then "default".
    """
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    tracing_on = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")

    if not api_key:
        print("[trace] LANGSMITH_API_KEY not set — skipping trace query.")
        return
    if not tracing_on or tracing_on.lower() not in ("1", "true", "yes"):
        print("[trace] LangSmith tracing not enabled — skipping trace query.")
        return

    try:
        from langsmith import Client
    except ImportError:
        print("[trace] langsmith package not installed — skipping trace query.")
        return

    resolved_project = (
        project_name
        or os.environ.get("LANGSMITH_PROJECT")
        or os.environ.get("LANGCHAIN_PROJECT")
        or "default"
    )

    client = Client()

    # Allow up to 10s for the trace to propagate to LangSmith.
    print(f"\n[trace] Querying LangSmith project={resolved_project!r} thread_id={thread_id!r} ...")
    root_run = None
    for attempt in range(5):
        try:
            runs = list(client.list_runs(
                project_name=resolved_project,
                filter=f'eq(metadata_key, "thread_id") and eq(metadata_value, "{thread_id}")',
                run_type="chain",
                limit=1,
            ))
        except Exception:
            # Older SDK versions don't support metadata filter — fall back to name search
            runs = []

        if not runs:
            # Fallback: list recent root runs and match by thread_id in metadata
            try:
                recent = list(client.list_runs(
                    project_name=resolved_project,
                    run_type="chain",
                    limit=20,
                    is_root=True,
                ))
                for r in recent:
                    meta = r.extra.get("metadata", {}) if r.extra else {}
                    if meta.get("thread_id") == thread_id:
                        runs = [r]
                        break
            except Exception:
                pass

        if runs:
            root_run = runs[0]
            break

        if attempt < 4:
            time.sleep(2)

    if root_run is None:
        print(f"[trace] No trace found for thread_id={thread_id!r} in project {resolved_project!r}.")
        print("[trace] The run may not have been traced (check LANGSMITH_TRACING and LANGSMITH_API_KEY).")
        return

    print(f"[trace] Root run: id={root_run.id} name={root_run.name!r} status={root_run.status}")
    if root_run.start_time and root_run.end_time:
        root_ms = (root_run.end_time - root_run.start_time).total_seconds() * 1000
        print(f"[trace] Total latency: {root_ms:.0f}ms")

    # Fetch all child runs (nodes) under the root trace.
    try:
        child_runs = sorted(
            client.list_runs(project_name=resolved_project, trace_id=root_run.id, limit=100),
            key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc),
        )
    except Exception as exc:
        print(f"[trace] Could not fetch child runs: {exc}")
        return

    print(f"[trace] Node sequence ({len(child_runs)} runs):")
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
        print("  ".join(parts))

    # Summarise errors
    errors = [r for r in child_runs if r.error]
    if errors:
        print(f"[trace] {len(errors)} node(s) errored — check LangSmith for details.")
    else:
        print("[trace] All nodes completed without errors.")
