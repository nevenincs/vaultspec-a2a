"""Layer marks for every test directory: declared as data, applied by one walk.

The layer vocabulary is a partition, not a per-package taste: a test is ``core``
(domain logic) or ``middleware`` (infrastructure), and ``unit`` is an ORTHOGONAL
claim of purity carried on top. Every package used to write the same walk over
that partition in its own ``conftest.py``, and the copies agreed only by upkeep -
which is the arrangement a marker vocabulary exists to prevent, since the whole
point of the marks is that one selection means one thing across the tree.

What varies between directories is DATA - which layer a directory sits on, which
files are infrastructure, which are not pure - so that is what the rule table
below holds. The walk itself lives in :func:`apply_layer_markers`, which the
repository-root ``conftest.py`` applies once to the whole collected session: a
new package opts in by adding a row, not by copying a hook.

Purity is decided by two mechanisms that are complements rather than
alternatives, and dropping either loses real cases:

- A file that performs I/O in its OWN body - opening a database, spawning a
  child - is named by its directory's rule, because nothing about the item
  reveals it.
- A test that acquires I/O by NAMING A FIXTURE reveals nothing in its body at
  all, and the fixture is usually defined in a ``conftest.py`` above it. That is
  asked of pytest per ITEM rather than per file, since a file-level exclusion
  would strip the claim from the pure tests that merely share a file with an
  impure one.

``unit`` is machine-readable, so a wrong claim is worse than no claim: a
selection that excludes impure tests silently INCLUDES anything neither
mechanism catches, and a run believed hermetic is not. A file that opens SQLite
therefore belongs in its directory's ``impure_files`` however pure its
assertions look.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import pytest

from .purity import forfeits_purity

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["LayerRule", "apply_layer_markers"]


@dataclass(frozen=True, slots=True)
class LayerRule:
    """How the tests under one directory are marked.

    ``layer`` is the directory's default. A file in ``middleware_files`` is
    infrastructure inside a ``core`` directory: it takes the ``middleware`` mark
    alone, because the layer already says the test drives real services.
    ``pure_middleware_files`` also sit on the middleware layer, by what they
    import, yet drive no I/O and so still earn ``unit``.

    ``live_files`` take no layer mark at all: they declare their own ``service``
    marker and must not be handed a pure-looking one. ``impure_files`` keep their
    layer but are never offered ``unit``. ``pure_files`` inverts the default for
    a directory that is mostly impure: ``None`` offers ``unit`` to every file not
    otherwise excluded, a set offers it to those files alone.
    """

    layer: Literal["core", "middleware", "service"]
    middleware_files: frozenset[str] = frozenset()
    pure_middleware_files: frozenset[str] = frozenset()
    impure_files: frozenset[str] = frozenset()
    live_files: frozenset[str] = frozenset()
    pure_files: frozenset[str] | None = None


#: A directory whose tests drive real infrastructure: the layer already says so,
#: and no file in it claims purity.
_INFRASTRUCTURE = LayerRule("middleware", pure_files=frozenset())

_DIRECTORY_RULES: Final[Mapping[str, LayerRule]] = {
    # --- Infrastructure directories ---------------------------------------
    "api/tests": _INFRASTRUCTURE,  # real SQLite and ASGI fixtures
    "cli/tests": _INFRASTRUCTURE,
    "control/cleanup/tests": _INFRASTRUCTURE,
    "control/repositories/tests": _INFRASTRUCTURE,
    "control/tests": _INFRASTRUCTURE,
    "database/tests": _INFRASTRUCTURE,
    "protocols/mcp/tests": _INFRASTRUCTURE,
    "telemetry/tests": _INFRASTRUCTURE,
    "worker/tests": _INFRASTRUCTURE,
    "workspace/tests": _INFRASTRUCTURE,
    # Pure schema validation, no I/O.
    "api/schemas/tests": LayerRule("middleware"),
    # Pure decoders and header/URL assembly earn ``unit``; the live engine tests
    # declare their own ``service`` marker.
    "authoring/tests": LayerRule(
        "middleware",
        impure_files=frozenset(
            {
                # The tool-call journal is a real SQLite file, and the relay and
                # stdio tests drive it through a real child process.
                "test_authoring_relay.py",
                "test_dispatch_injection.py",
                "test_stdio_refresh.py",
                "test_tool_call_retirement.py",
            }
        ),
        live_files=frozenset({"test_live_engine.py"}),
    ),
    "providers/tests": LayerRule(
        "middleware",
        # Files that stay on the middleware layer but really do spawn a child or
        # open a real database. Distinct from ``live_files``, which declare their
        # own ``service`` marker and take no layer mark at all.
        impure_files=frozenset(
            {
                # Real child processes.
                "test_acp_mcp.py",
                "test_acp_stderr_tail.py",
                "test_harness_interpreter_pin.py",
                "test_acp_model_selection.py",
                "test_acp_turn_deadline.py",
                "test_acp_vault_deny.py",
                "test_acp_fs_read_limits.py",
                "test_acp_callback_ownership.py",
                "test_acp_terminal_output.py",
                "test_capsule_acp_resolution.py",
                "test_claude_binary_identity.py",
                "test_catalog_registration_live.py",
                "test_codex_config_home.py",
                "test_codex_credential_writeback.py",
                "test_codex_stderr_drain.py",
                "test_codex_turn_idle_timeout.py",
                "test_claude_permission_posture.py",
                "test_claude_rule_anchor.py",
                "test_launcher_confinement.py",
                "test_model_stack_warmup.py",
                "test_prompt_render.py",
                "test_resource_lifetimes.py",
                # Real async engine and session maker.
                "test_codex_chat_model.py",
            }
        ),
        live_files=frozenset(
            {
                "test_acp_authoring_bridge.py",
                "test_acp_strict_mcp_surface.py",
                "test_codex_config_home_service.py",
                "test_authoring_stdio_bridge.py",
                "test_acp_migration_surface.py",
                "test_acp_catalog_live.py",
                "test_kimi_handshake_live.py",
                "test_provider_containment.py",
                "test_terminal_containment.py",
            }
        ),
    ),
    # The fixture lanes, built through the production provider factory.
    "testing/lanes/tests": LayerRule(
        "middleware",
        # Drives a real compiled graph through a real checkpointer.
        impure_files=frozenset({"test_deterministic_scripts.py"}),
    ),
    # --- Core directories --------------------------------------------------
    "context/tests": LayerRule(
        "core",
        # Spawns a fresh interpreter.
        impure_files=frozenset({"test_import_isolation.py"}),
    ),
    "graph/tests": LayerRule(
        "core",
        # Graph tests that import Layer 2.
        middleware_files=frozenset(
            {"test_worker_integration.py", "test_worker_authoring_wiring.py"}
        ),
        # Layer-1 tests that still perform real I/O - a live SQLite checkpointer,
        # or real ACP subprocesses driven through a compiled graph. They keep
        # ``core`` but are NOT pure, so the orthogonal ``unit`` marker is withheld.
        impure_files=frozenset(
            {
                "test_compiler.py",
                "test_harness_topology_reach.py",
                # Live AsyncSqliteSaver against a real database file.
                "test_action_completion.py",
                "test_checkpointed_value_types.py",
                "test_diverge.py",
                "test_mounted_context_persistence.py",
                "test_persona_web_composition.py",
                "test_research_adr.py",
                "test_research_adr_clarification.py",
                "test_research_branch_models.py",
                "test_research_permission_rung.py",
                "test_research_web_locators.py",
                # Real .vault/ trees on disk, scanned by the index refresh.
                "test_vault_index_refresh.py",
                "test_vault_reader.py",
                "test_vault_write_isolation.py",
                # Real HTTP against a live engine. This file declares its own
                # ``service`` marker, but the layer mark is still added here, so
                # the purity claim is withheld by name as well.
                "test_feedback_grounding_live.py",
            }
        ),
    ),
    # The IPC serializer tests exercise pure data-transformation helpers.
    "ipc/tests": LayerRule("core"),
    "lifecycle/tests": LayerRule(
        "core",
        # Files whose tests drive real infrastructure (fs/process/HTTP) rather
        # than pure domain logic.
        middleware_files=frozenset(
            {
                "test_discovery.py",
                "test_registry.py",
                "test_procs_config.py",
                "test_manager.py",
                "test_registration.py",
                "test_live_concurrency.py",
                "test_engine_serve.py",
            }
        ),
        # Core-layer tests that really do launch a child process.
        impure_files=frozenset({"test_pairing.py", "test_singleton.py"}),
    ),
    "streaming/tests": LayerRule(
        "core",
        # Real SQLite engines and savers.
        impure_files=frozenset(
            {
                "test_ingest_durability.py",
                "test_public_stream_ingest.py",
                "test_run_event_writer.py",
                "test_run_sequence_allocation.py",
                "test_stream_identity.py",
            }
        ),
    ),
    "team/tests": LayerRule("core"),
    "thread/tests": LayerRule(
        "core",
        # Live SQLite checkpointers against a database file.
        impure_files=frozenset(
            {
                "test_action_receipts.py",
                "test_checkpoint_evidence.py",
                "test_input_checkpoint_evidence.py",
                "test_state.py",
            }
        ),
    ),
    "utils/tests": LayerRule(
        "core",
        # Real subprocess I/O.
        middleware_files=frozenset({"test_process.py"}),
        # Layer 2 by import (``control.config.Settings``) but pure.
        pure_middleware_files=frozenset({"test_logging.py"}),
        # Core-layer tests that really do spawn a child process.
        impure_files=frozenset(
            {
                "test_logging_entrypoints.py",
                "test_process_containment.py",
                "test_runtime_exec.py",
            }
        ),
    ),
    # --- Service certification --------------------------------------------
    "service_tests": LayerRule("service"),
}

#: Every directory rule, keyed by the absolute directory it governs.
_LAYER_RULES: Final[Mapping[Path, LayerRule]] = {
    Path(__file__).resolve().parents[1] / directory: rule
    for directory, rule in _DIRECTORY_RULES.items()
}


def apply_layer_markers(
    items: Iterable[pytest.Item],
    rules: Mapping[Path, LayerRule] = _LAYER_RULES,
) -> None:
    """Mark every item under a rule's directory by layer, and by purity where earned.

    The nearest governing directory above an item decides its rule. An item
    under no rule's directory is left alone, and every hook receives the whole
    collected session, so a rule speaks only for the directory it is keyed to.

    ``unit`` is added only when the item's file is not infrastructure or named
    impure, is not excluded by a ``pure_files`` allowlist, and the item's own
    resolved fixture closure and markers do not forfeit it. The layer mark is
    added first, so a ``service`` layer forfeits ``unit`` through the same check
    as any item that declares ``service`` for itself.
    """
    for item in items:
        for directory in item.path.parents:
            rule = rules.get(directory)
            if rule is not None:
                _mark(item, rule)
                break


def _mark(item: pytest.Item, rule: LayerRule) -> None:
    name = item.path.name
    if name in rule.live_files:
        return
    if name in rule.middleware_files:
        item.add_marker("middleware")
        return
    on_middleware = name in rule.pure_middleware_files
    item.add_marker("middleware" if on_middleware else rule.layer)
    if name in rule.impure_files:
        return
    if rule.pure_files is not None and name not in rule.pure_files:
        return
    if not forfeits_purity(item):
        item.add_marker(pytest.mark.unit)
