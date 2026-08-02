"""Progress-based deadlines for non-deterministic live tests.

A fixed wall clock is wrong in both directions for a live run: it kills a
legitimately slow model turn and it lets a hung one burn the whole budget. The
deadline here fails a wait for exactly two honest reasons instead:

- the watched resource DIED: its owner pid is gone, or its heartbeat froze past
  the staleness window. Both signals are required because this repository's
  engines have been observed serving HTTP after their heartbeat writer died -
  neither signal alone is trustworthy.
- the wait STALLED: the observed state stopped changing for longer than the
  idle window. A turn that keeps streaming frames keeps touching the deadline
  and is never killed for being slow; a wedged one fails after one idle window
  with a diagnostic naming the last progress and every liveness verdict.

Elapsed total time is deliberately not a failure reason; the per-item
pytest-timeout backstop (derived from the declared resources) remains the
last-resort guard against test code that stops polling entirely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..lifecycle import (
    ProcsConfigError,
    StalenessState,
    classify_record,
    load_procs_config,
    read_record,
    record_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

__all__ = [
    "LivenessWatch",
    "ProgressDeadline",
    "ProgressStalledError",
    "ResourceDiedError",
    "registry_watch",
    "wait_for",
]


class ResourceDiedError(AssertionError):
    """The watched resource is provably gone; waiting longer cannot succeed."""


class ProgressStalledError(AssertionError):
    """The observed state stopped changing for longer than the idle window."""


@dataclass(frozen=True, slots=True)
class LivenessWatch:
    """One liveness verdict source: a callable naming the failure, or ``None``.

    ``verdict`` re-derives its answer on every call (re-reads a record, probes
    a pid) so a watch never caches a stale conclusion.
    """

    label: str
    verdict: Callable[[], str | None]


def registry_watch(role: str, name: str, *, home: Path | None = None) -> LivenessWatch:
    """Watch a dev-process registry record with the production classifier.

    The verdict is ``classify_record`` itself - pid-liveness plus the role's
    heartbeat staleness window - re-read from the record file on every check,
    so the watch and the lifecycle verbs can never disagree about what LIVE
    means. A record that disappears mid-run is a death, not a pass.
    """
    try:
        config = load_procs_config()
    except ProcsConfigError:
        config = None

    def _verdict() -> str | None:
        record = read_record(record_path(role, name, home=home))
        if record is None:
            return f"registry record {role}-{name} is gone"
        role_config = None
        if config is not None and role in config.roles:
            role_config = config.roles[role]
        state = classify_record(record, role_config)
        if state is StalenessState.DEAD:
            return f"{role}-{name} owner pid {record.pid} is dead"
        if state is StalenessState.STALE:
            return (
                f"{role}-{name} pid {record.pid} is alive but its heartbeat "
                f"froze (last_seen_ms={record.last_seen_ms})"
            )
        return None

    return LivenessWatch(label=f"{role}-{name}", verdict=_verdict)


@dataclass(slots=True)
class ProgressDeadline:
    """Fail on death or stall, never on honest slowness.

    ``touch()`` records observed progress; ``check()`` raises
    :class:`ResourceDiedError` the moment any watch reports a failure and
    :class:`ProgressStalledError` once no progress has been observed for
    ``idle_window_s``. Poll loops call ``check()`` each iteration.
    """

    idle_window_s: float
    watches: Sequence[LivenessWatch] = ()
    _last_progress: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """Record that the observed state changed just now."""
        self._last_progress = time.monotonic()

    def idle_s(self) -> float:
        """Seconds since progress was last observed."""
        return time.monotonic() - self._last_progress

    def check(self) -> None:
        """Raise if the resource died or the wait stalled; otherwise return."""
        for watch in self.watches:
            reason = watch.verdict()
            if reason is not None:
                raise ResourceDiedError(
                    f"watched resource '{watch.label}' died: {reason} "
                    f"(last progress {self.idle_s():.1f}s ago)"
                )
        idle = self.idle_s()
        if idle > self.idle_window_s:
            verdicts = (
                ", ".join(f"{watch.label}: live" for watch in self.watches)
                or "no liveness watches"
            )
            raise ProgressStalledError(
                f"no progress observed for {idle:.1f}s "
                f"(idle window {self.idle_window_s}s; {verdicts}). The resource "
                "is alive but the observed state stopped changing - this is a "
                "hang, not slowness."
            )


def wait_for[T](
    poll: Callable[[], T | None],
    *,
    deadline: ProgressDeadline,
    fingerprint: Callable[[], object] | None = None,
    interval_s: float = 0.5,
) -> T:
    """Poll until *poll* returns a value, under progress-based failure only.

    Each *poll* call whose *fingerprint* differs from the previous observation
    counts as progress and touches the deadline; with no fingerprint supplied,
    only completion counts, so the idle window bounds the whole wait. The
    deadline's watches are checked every iteration, so a dead resource fails
    the wait in one interval rather than one idle window.
    """
    last_print: object = object()
    while True:
        result = poll()
        if result is not None:
            return result
        if fingerprint is not None:
            current = fingerprint()
            if current != last_print:
                last_print = current
                deadline.touch()
        deadline.check()
        time.sleep(interval_s)
