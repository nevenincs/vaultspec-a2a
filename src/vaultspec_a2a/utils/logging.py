"""Logging utilities for the VaultSpec A2A project.

One configuration entrypoint, :func:`configure_logging`, selects an output-lane
contract per process kind (observability-lanes ADR). The contracts are the
audit surface: each lane is created here, not in the discipline of every caller.

- ``service`` (gateway/worker): structured JSON to ``stderr`` plus a size-capped
  rotating file lane under the runtime dir, honoring ``VAULTSPEC_LOG_LEVEL``.
- ``cli``: human-readable diagnostics to ``stderr`` at WARNING; ``stdout`` is left
  for command output and ``--json`` payloads.
- ``protocol`` (stdio MCP bridge): ``stderr``-only at WARNING, with an explicit
  assertion that no ``stdout`` handler exists on the root - its ``stdout`` carries
  JSON-RPC frames and must never gain a log handler.
- ``library``: import-safe no-op (imported by tests/drivers).

``stderr``-always for every log lane collapses protocol-corruption and
piped-output-corruption into one impossible-by-construction state.
"""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from opentelemetry import trace
from opentelemetry.trace.span import format_span_id, format_trace_id

from ..artifacts import ArtifactDeclaration, RetentionDisposition

if TYPE_CHECKING:
    from pathlib import Path

#: The populated shape of ``LogRecord.exc_info``; see ``JSONFormatter``, which
#: exists partly because the attribute is not always this.
type _ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]

__all__ = [
    "ARTIFACT_DECLARATIONS",
    "SERVICE_LOG_FILE_DECLARATION",
    "JSONFormatter",
    "LivenessPollFilter",
    "OTelCorrelationFilter",
    "ProcessKind",
    "configure_logging",
    "reconfigure_console_utf8",
]

ProcessKind = Literal["service", "cli", "protocol", "library"]

# Rotating file lane caps: bound each file by size and the count on disk, so a
# long-lived service process never grows an unbounded log.
_FILE_MAX_BYTES = 10 * 1024 * 1024
_FILE_BACKUP_COUNT = 5

# The one durable artifact this module creates. The cap is real and enforced by
# the handler itself rather than by a sweeper, which is why this seam is bounded
# where the sibling redirect logs are not: rotation happens inside the writer.
SERVICE_LOG_FILE_DECLARATION = ArtifactDeclaration(
    name="service-log-file",
    root="<a2a_home>/runtime/<service_name>.log (plus .1-.5 rotation siblings)",
    owner="utils.logging",
    disposition=RetentionDisposition.BOUNDED_BY_SIZE,
    mechanism=(
        f"RotatingFileHandler caps each file at {_FILE_MAX_BYTES} bytes and keeps "
        f"{_FILE_BACKUP_COUNT} backups, so one service name holds at most "
        f"{_FILE_MAX_BYTES * (_FILE_BACKUP_COUNT + 1)} bytes; nothing deletes the "
        "files when the service stops, so a service name that is never run again "
        "leaves its last generation on disk indefinitely"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (SERVICE_LOG_FILE_DECLARATION,)


class _LoggingSettings(Protocol):
    """Structural type for the settings attributes :func:`configure_logging` reads.

    Note: ty does not yet have a Pydantic plugin (astral-sh/ty#2403), so
    Pydantic models passed here require ``# ty: ignore[invalid-argument-type]``
    at call sites.
    """

    @property
    def log_level(self) -> Any: ...

    @property
    def no_color(self) -> bool: ...

    @property
    def ci(self) -> bool: ...

    @property
    def is_dev(self) -> bool: ...

    @property
    def a2a_home(self) -> Path: ...


# Standard LogRecord attributes that should not be included as extra fields.
_STANDARD_LOG_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


#: Access-log paths whose SUCCESSFUL polls carry no information.
#:
#: Supervisors probe liveness on a fixed interval forever, so a 200 on one of
#: these says only that polling is still happening. A non-2xx on the same path is
#: kept: that is the one case where the probe is telling you something.
_LIVENESS_POLL_PATHS: frozenset[str] = frozenset({"/health", "/internal/health"})


class LivenessPollFilter(logging.Filter):
    """Drop successful liveness-probe access lines from the service lanes.

    Measured cost of not doing this: a five-minute run making thirty tool calls
    left four lines in the gateway log, while the health poll alone contributed a
    line every five seconds. Real events were a rounding error against the probe
    traffic, which is how a genuine boot failure and a tool-permission denial both
    went unnoticed in a file that was being written to constantly.

    Deliberately narrow. It matches uvicorn's access logger only, keeps every
    non-2xx, and never touches the application loggers - a filter that silences
    real events to reduce volume trades one blind spot for another.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return ``False`` only for a 2xx access line on a liveness path."""
        if record.name != "uvicorn.access":
            return True
        args = record.args
        # uvicorn.access formats as (client, method, path, http_version, status).
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path, status = args[2], args[4]
        if not isinstance(path, str):
            return True
        if path.split("?", 1)[0] not in _LIVENESS_POLL_PATHS:
            return True
        if not isinstance(status, int | str):
            # An unrecognised status is not a proven-boring poll; keep it.
            return True
        try:
            return not 200 <= int(status) < 300
        except ValueError:
            return True


class OTelCorrelationFilter(logging.Filter):
    """Inject OTel correlation fields into log records when a span is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Populate correlation fields without overwriting caller-provided values."""
        span = trace.get_current_span()
        context = span.get_span_context()
        if not context.is_valid:
            return True

        if "trace_id" not in record.__dict__:
            record.trace_id = format_trace_id(context.trace_id)
        if "span_id" not in record.__dict__:
            record.span_id = format_span_id(context.span_id)
        if "trace_sampled" not in record.__dict__:
            record.trace_sampled = bool(context.trace_flags.sampled)

        if "service_name" not in record.__dict__:
            resource = getattr(span, "resource", None)
            attributes = getattr(resource, "attributes", None)
            if attributes is not None:
                service_name = attributes.get("service.name")
                if isinstance(service_name, str) and service_name:
                    record.service_name = service_name

        return True


class JSONFormatter(logging.Formatter):
    """Formatter that outputs JSON strings for structured logging.

    Any extra fields added via ``logging.getLogger(__name__).info(...,
    extra={"thread_id": "...", "agent_id": "..."})`` are automatically
    included in the JSON output, enabling structured correlation context.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a single-line JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        # Include any structured extra fields (e.g. thread_id, agent_id, client_id)
        # that callers pass via logger.info(..., extra={"thread_id": "..."}).
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS and not key.startswith("_"):
                log_data[key] = value

        exception = self._exception_text(record.exc_info)
        if exception is not None:
            log_data["exception"] = exception

        return json.dumps(log_data)

    def _exception_text(self, exc_info: object) -> str | None:
        """Render whatever ``record.exc_info`` holds, or ``None`` if it holds nothing.

        ``exc_info`` is not the three-tuple its name promises. ``Logger._log``
        normalises only TRUTHY values, so a caller passing ``exc_info=False`` -
        which is what a computed flag evaluates to, and what the OTLP gRPC
        exporter passes on every transport error it does not classify as unknown
        - reaches the record as the bare ``False``. Handing that to
        ``formatException`` raised ``TypeError: 'bool' object is not
        subscriptable``, and because a formatter that raises loses the record
        entirely, every such export failure went unreported by the lane meant to
        report it.

        Each shape the attribute can legally carry is answered here: absent or
        switched off, an exception instance, a populated three-tuple, an empty
        one, and the raw flag on a record built outside ``Logger._log``.
        """
        if not exc_info:
            return None
        if isinstance(exc_info, BaseException):
            return self.formatException(
                (type(exc_info), exc_info, exc_info.__traceback__)
            )
        if not isinstance(exc_info, tuple):
            # A record assembled directly rather than through ``Logger._log``
            # never had its flag resolved; resolve it the way that would have.
            exc_info = sys.exc_info()
        if len(exc_info) != 3 or exc_info[0] is None:
            return None
        return self.formatException(cast("_ExcInfo", exc_info))


def reconfigure_console_utf8() -> None:
    """Best-effort UTF-8 reconfigure of the process console streams; never raises.

    Windows consoles default to legacy code pages (cp1252) that crash on naive
    Unicode prints (observed: ``U+2192`` in diagnostics). Applied once at each
    entrypoint rather than scattered; a stream that cannot be reconfigured (not a
    real console, already detached, older Python) is left as-is.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError, AttributeError):
            # Not a reconfigurable text stream (redirected pipe, closed, etc.).
            continue


def _resolve_settings(settings_override: _LoggingSettings | None) -> _LoggingSettings:
    if settings_override is not None:
        return settings_override
    from ..control.config import settings

    return settings


def _numeric_level(level: Any) -> int:
    """Coerce a LogLevel/str level to a numeric logging level (INFO fallback)."""
    if hasattr(level, "value"):
        level = level.value
    level_str = str(level).upper()
    return logging.getLevelNamesMapping().get(level_str, logging.INFO)


def _reset_root() -> logging.Logger:
    """Clear the root logger's handlers so re-configuration never duplicates lanes.

    Each removed handler is ``close()``d: a ``RotatingFileHandler`` left dangling on
    a reconfigure would leak its open file handle (on Windows the file then cannot be
    rotated or the tmp dir removed). ``StreamHandler.close()`` does not close the
    underlying ``stderr``/``stdout`` stream, so this is safe for the console lanes.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    return root


def _reattach_uvicorn(handlers: list[logging.Handler], level: int) -> None:
    """Route uvicorn's own loggers through our lanes without double-delivery.

    ``handlers.clear()`` + ``addHandler`` (not list assignment) respects the
    logging module's internal locking. ``propagate = False`` prevents a second
    emission via the root.
    """
    for name in ("uvicorn.access", "uvicorn.error"):
        lib_logger = logging.getLogger(name)
        lib_logger.setLevel(level)
        lib_logger.handlers.clear()
        for handler in handlers:
            lib_logger.addHandler(handler)
        lib_logger.propagate = False


def _stderr_json_handler(level: int) -> logging.StreamHandler[Any]:
    handler: logging.StreamHandler[Any] = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(OTelCorrelationFilter())
    return handler


def _assert_no_stdout_handler(root: logging.Logger) -> None:
    """Fail loud if any root handler would write to ``stdout``.

    The protocol lane's ``stdout`` is JSON-RPC; a log line interleaved there
    corrupts the frame stream. This is a construction-time guard, not a runtime
    hope.
    """
    for handler in root.handlers:
        stream = getattr(handler, "stream", None)
        if stream is sys.stdout:
            raise AssertionError(
                "protocol logging must not attach a stdout handler to the root "
                f"logger; found {handler!r} writing to stdout"
            )


#: Exporter loggers demoted from ERROR to WARNING on the service lanes.
#:
#: An unreachable telemetry collector is a DEPLOYMENT condition, not a service
#: error: the gateway is serving correctly and the export simply has nowhere to
#: go. Reported at ERROR it drowned the level entirely - every one of the 51
#: ERROR records in a sampled gateway log was an export failure to an absent
#: collector, retried every ten seconds forever, and a real boot failure in the
#: same file had produced no ERROR line at all. Demoting these is what makes
#: ERROR mean "something is wrong with this service" again.
#:
#: The condition is still reported, once per retry, at WARNING. Silencing it
#: outright would hide a genuinely misconfigured collector.
_EXPORT_FAILURE_LOGGERS: tuple[str, ...] = (
    "opentelemetry.exporter.otlp.proto.grpc.exporter",
    "opentelemetry.exporter.otlp.proto.http.exporter",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.metrics.export",
)


class _DemoteToWarning(logging.Filter):
    """Rewrite ERROR records from a named logger down to WARNING in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


def _demote_export_failures() -> None:
    """Stop an absent telemetry collector from monopolising the ERROR level."""
    for name in _EXPORT_FAILURE_LOGGERS:
        logging.getLogger(name).addFilter(_DemoteToWarning())


def _configure_service(settings: _LoggingSettings, service_name: str) -> None:
    level = _numeric_level(settings.log_level)
    root = _reset_root()
    root.setLevel(level)

    handlers: list[logging.Handler] = [_stderr_json_handler(level)]

    runtime_dir = settings.a2a_home / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            runtime_dir / f"{service_name}.log",
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(JSONFormatter())
        file_handler.addFilter(OTelCorrelationFilter())
        handlers.append(file_handler)
    except OSError:
        # The stderr lane still carries everything; a missing/again-unwritable
        # runtime dir must not take the service down over its log file.
        logging.getLogger(__name__).warning(
            "service log file lane unavailable under %s; stderr lane only",
            runtime_dir,
        )

    for handler in handlers:
        handler.addFilter(LivenessPollFilter())
        root.addHandler(handler)
    _reattach_uvicorn(handlers, level)
    _demote_export_failures()


def _configure_cli(settings: _LoggingSettings) -> None:
    # Human diagnostics on stderr; stdout is reserved for command output/--json.
    root = _reset_root()
    root.setLevel(logging.WARNING)
    interactive = (
        sys.stderr.isatty()
        and not settings.no_color
        and not settings.ci
        and settings.is_dev
    )
    handler: logging.Handler
    if interactive:
        from rich.console import Console
        from rich.logging import RichHandler

        handler = RichHandler(
            level=logging.WARNING,
            console=Console(stderr=True),
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_path=True,
        )
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(OTelCorrelationFilter())
    root.addHandler(handler)


def _configure_protocol() -> None:
    # stderr-only; stdout carries JSON-RPC and must never gain a handler.
    root = _reset_root()
    root.setLevel(logging.WARNING)
    handler = _stderr_json_handler(logging.WARNING)
    root.addHandler(handler)
    _assert_no_stdout_handler(root)


def configure_logging(
    kind: ProcessKind,
    *,
    service_name: str = "service",
    settings_override: _LoggingSettings | None = None,
) -> None:
    """Configure the process's output lanes for its *kind* (see module docstring).

    ``service_name`` names the rotating file lane for the ``service`` kind
    (e.g. ``"gateway"``, ``"worker"``). ``settings_override`` injects settings for
    tests; production reads the config singleton lazily so import stays side-effect
    free. ``library`` returns immediately, leaving the root logger untouched.
    """
    if kind == "library":
        return
    if kind == "cli":
        _configure_cli(_resolve_settings(settings_override))
        return
    if kind == "protocol":
        _configure_protocol()
        return
    if kind == "service":
        _configure_service(_resolve_settings(settings_override), service_name)
        return
    raise ValueError(f"unknown process kind: {kind!r}")
