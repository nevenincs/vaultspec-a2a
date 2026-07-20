Python module reference
=======================

This reference documents the supported public application programming
interfaces (APIs) and their runtime ownership boundaries. Import concrete
features from the module that owns them.

Major package surfaces
----------------------

Distribution namespace
~~~~~~~~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a

Domain configuration
~~~~~~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.domain_config

.. py:class:: DomainConfig

.. py:class:: DomainSettingsConfig

.. py:data:: domain_config

API
~~~

.. automoduledoc:: vaultspec_a2a.api

Authoring
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.authoring

Command-line interface
~~~~~~~~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.cli

Context
~~~~~~~

.. automoduledoc:: vaultspec_a2a.context

Control
~~~~~~~

.. automoduledoc:: vaultspec_a2a.control

Control objects live in direct child modules. The package ``__all__``
advertises module names but doesn't bind those modules as attributes.

Database
~~~~~~~~

.. automoduledoc:: vaultspec_a2a.database

Desktop capsule
~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.desktop

Graph
~~~~~

.. automoduledoc:: vaultspec_a2a.graph

Inter-process communication
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.ipc

Lifecycle
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.lifecycle

Protocols
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.protocols

Providers
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.providers

Streaming
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.streaming

Team configuration
~~~~~~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.team

Telemetry
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.telemetry

Thread domain
~~~~~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.thread

Utilities
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.utils

Worker
~~~~~~

.. automoduledoc:: vaultspec_a2a.worker

Workspace
~~~~~~~~~

.. automoduledoc:: vaultspec_a2a.workspace

Public entry points
-------------------

API application
~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.api.app
   :synopsis: FastAPI application construction.

.. py:function:: create_app(lifespan=None, *, allow_unauthenticated_v1_for_testing=False)

   Construct the gateway application. Production callers must leave the
   unauthenticated ``/v1`` test bypass disabled.

.. py:module:: vaultspec_a2a.api.auth
   :synopsis: Bearer authentication for engine-facing gateway routes.

.. py:function:: authenticate_request(request, authorization=None)

   Require the service-discovery bearer token for an engine-facing request.
   See :func:`vaultspec_a2a.api.app.create_app` for application wiring.

.. py:module:: vaultspec_a2a.api.routes.gateway
   :synopsis: Versioned start, prepare, commit, release, status, and stream routes.

.. py:module:: vaultspec_a2a.api.schemas.gateway
   :synopsis: Bounded gateway lifecycle and lease-status wire models.

.. py:module:: vaultspec_a2a.api.body_limit
   :synopsis: Pre-parser memory bound for authenticated v1 write bodies.

.. py:module:: vaultspec_a2a.api.websocket
   :synopsis: WebSocket connection and command handling.

.. py:class:: ConnectionManager(aggregator)

Command-line entry point
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.cli.main
   :synopsis: ``vaultspec-a2a`` command dispatch.

.. py:function:: main(*args, **kwargs)

.. py:module:: vaultspec_a2a.cli.provision
   :synopsis: Run-workspace agent-harness provisioning.

.. py:module:: vaultspec_a2a.context.harness
   :synopsis: Agent-harness discovery and verification.

Desktop capsule contract
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.desktop.contract
   :synopsis: Versioned desktop component-manifest models and compatibility.

.. py:class:: ComponentManifest

.. py:function:: component_manifest_schema()

.. py:function:: contract_versions_compatible(declared, supported)

.. py:function:: export_component_manifest_schema()

.. py:module:: vaultspec_a2a.desktop.manifest
   :synopsis: Deterministic desktop component-manifest emission and hashing.

.. py:class:: AssetSource

.. py:class:: BoundAssetSource

.. py:function:: emit_component_manifest(*, target, api_versions, assets, uv_lock_path, package_lock_path, digest_algorithm=DigestAlgorithm.SHA256)

.. py:function:: emit_component_manifest_from_bound_inputs(*, target, api_versions, assets, a2a_wheel, uv_lock_digest, package_lock_digest, digest_algorithm=DigestAlgorithm.SHA256)

.. py:function:: component_manifest_canonical_bytes(manifest)

.. py:function:: component_manifest_digest(manifest)

Desktop product profile
~~~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.desktop.profile
   :synopsis: Explicit immutable-runtime and mutable-state authorities.

.. py:class:: DesktopProfile

.. py:class:: DesktopStatePaths

.. py:function:: derive_state_paths(app_home)

Staged desktop migration
~~~~~~~~~~~~~~~~~~~~~~~~

The external updater supplies a one-time descriptor to
:func:`vaultspec_a2a.desktop.migration.run_staged_migration`. Descriptor
validation is owned by :mod:`vaultspec_a2a.desktop.transaction`; schema work
is owned by :mod:`vaultspec_a2a.desktop.migration`.

.. py:module:: vaultspec_a2a.desktop.transaction
   :synopsis: One-time staged-generation transaction descriptors.

.. py:class:: TransactionDescriptor

.. py:class:: TransactionDescriptorError

.. py:function:: load_transaction_descriptor(path)

.. py:function:: mark_transaction_consumed(transaction)

.. py:module:: vaultspec_a2a.desktop.migration
   :synopsis: Quiescent desktop-store migration execution.

.. py:class:: MigrationResult

.. py:class:: StoreOutcome

.. py:function:: run_staged_migration(descriptor_path)

Desktop consistency-group snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Snapshot capture and restore operate on the complete mutable desktop state
group and require the gateway to be quiescent. See
:mod:`vaultspec_a2a.desktop.snapshot` for the durable descriptor and interrupted
restore-marker contracts.

.. py:module:: vaultspec_a2a.desktop.snapshot
   :synopsis: Capture, inspect, and restore desktop consistency groups.

.. py:class:: ConsistencyGroupStore

.. py:class:: ConsistencyGroupStoreSpecification

.. py:class:: StoreSnapshot

.. py:class:: GroupDescriptor

.. py:class:: RestoreMarker

.. py:class:: RestoreOutcome

.. py:class:: SnapshotError

.. py:class:: SnapshotIntegrityError

.. py:class:: SnapshotStoreLockedError

.. py:class:: RestorePendingError

.. py:function:: consistency_group_specifications()

.. py:function:: consistency_group_members(state)

.. py:function:: create_snapshot(app_home, group_id, *, now=None)

.. py:function:: inspect_snapshot(app_home, group_id)

.. py:function:: list_snapshots(app_home)

.. py:function:: pending_restore(app_home)

.. py:function:: restore_snapshot(app_home, group_id, *, resume=False, now=None)

Desktop assembly internals
~~~~~~~~~~~~~~~~~~~~~~~~~~

These workflow-facing modules implement capsule assembly. They aren't part of
the package-root component-manifest API and may change with the release
workflow.

.. py:module:: vaultspec_a2a.desktop.artifacts
   :synopsis: Exact retained local-input authority and byte-identity verification.

.. py:module:: vaultspec_a2a.desktop.package_archives
   :synopsis: Verified Python and ACP package archive sessions.

.. py:module:: vaultspec_a2a.desktop.closure_inventory
   :synopsis: Canonical Python and ACP source-closure inventories.

.. py:module:: vaultspec_a2a.desktop.installed_inventory
   :synopsis: Canonical expected installed-tree inventories.

.. py:module:: vaultspec_a2a.desktop.lock_reconciliation
   :synopsis: Closure reconciliation against exact dependency-lock bytes.

.. py:module:: vaultspec_a2a.desktop._archive_authority
   :synopsis: Bounded archive scanning and retained regular-file snapshots.

.. py:module:: vaultspec_a2a.desktop.capsule
   :synopsis: Bounded archive projection into private staging trees.

.. py:module:: vaultspec_a2a.desktop.capsule_evidence
   :synopsis: Installed-tree evidence and deterministic archive publication.

.. py:module:: vaultspec_a2a.desktop._filesystem_authority
   :synopsis: Native descriptor and handle authority for no-replace publication.

Graph construction
~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.graph.nodes.vault_reader
   :synopsis: Vault index construction.

.. py:function:: build_initial_vault_index(workspace_root, feature_tag)

.. py:module:: vaultspec_a2a.graph.compiler
   :synopsis: Executable team-graph compilation.

.. py:function:: compile_team_graph(team_config, agent_configs, *, provider_factory, **options)

Provider construction
~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.providers.acp_chat_model
   :synopsis: Agent Client Protocol chat-model integration.

.. py:class:: AcpChatModel

.. py:module:: vaultspec_a2a.providers.mock_chat_model
   :synopsis: Deterministic mock chat-model integration.

.. py:class:: MockChatModel

.. py:module:: vaultspec_a2a.providers.factory
   :synopsis: Provider selection and construction.

.. py:class:: ProviderFactory

Event aggregation
~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.streaming.aggregator
   :synopsis: Runtime event ingestion, sequencing, and emission.

.. py:class:: EventAggregator(telemetry=None)

Workspace management
~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.workspace.git_manager
   :synopsis: Git worktree lifecycle management.

.. py:class:: GitManager(repo_root)

.. py:class:: MergeStrategy

.. py:class:: WorktreeInfo(path, branch, head_sha, is_main)

Collaborating modules
---------------------

API and protocols
~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.api.schemas
   :synopsis: Hypertext Transfer Protocol (HTTP) and WebSocket wire schemas.

.. py:module:: vaultspec_a2a.protocols.mcp
   :synopsis: Model Context Protocol package boundary.

.. py:module:: vaultspec_a2a.protocols.mcp.server
   :synopsis: FastMCP server construction.

.. py:module:: vaultspec_a2a.protocols.mcp.authoring_stdio
   :synopsis: Engine authoring transport over standard input and output.

Authoring and worker integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.authoring.client
   :synopsis: Engine authoring client.

.. py:module:: vaultspec_a2a.authoring.session
   :synopsis: Authoring-session lifecycle.

.. py:module:: vaultspec_a2a.authoring.submitter
   :synopsis: Proposal document submission.

.. py:module:: vaultspec_a2a.worker.authoring_binding
   :synopsis: Worker authoring-session binding.

Control services
~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.control.config
   :synopsis: Runtime application settings.

.. py:module:: vaultspec_a2a.control.cancel_service
   :synopsis: Thread cancellation orchestration.

.. py:module:: vaultspec_a2a.control.message_service
   :synopsis: Follow-up message orchestration.

.. py:module:: vaultspec_a2a.control.run_start_policy
   :synopsis: Run-start eligibility policy.

.. py:module:: vaultspec_a2a.control.admission
   :synopsis: Readiness-gated prepared reservations and exact commit binding.

.. py:module:: vaultspec_a2a.control.health
   :synopsis: Gateway diagnostics and desktop admission-readiness authority.

.. py:module:: vaultspec_a2a.control.run_discovery_service
   :synopsis: Bounded durable identity projection for active-run rebinding.

.. py:class:: ActiveRunSummary

.. py:class:: ActiveRunDiscoveryResult

.. py:function:: discover_active_runs(db, *, workspace_root=None, feature_tag=None, limit=50)

.. py:module:: vaultspec_a2a.control.verdict_subscriber
   :synopsis: Authoring verdict delivery.

.. py:module:: vaultspec_a2a.worker.app
   :synopsis: Authenticated worker dispatch and accepted-dispatch logging.

Persistence
~~~~~~~~~~~

.. py:module:: vaultspec_a2a.database.checkpoint_schema
   :synopsis: Version and validate the desktop checkpoint database schema.

.. py:class:: CheckpointSchemaError

.. py:function:: install_checkpoint_schema_identity(checkpoint_path)

.. py:function:: open_checkpoint_read_only(checkpoint_path)

.. py:function:: validate_checkpoint_schema_connection(connection)

.. py:function:: validate_checkpoint_schema_identity(checkpoint_path)

.. py:module:: vaultspec_a2a.database.models
   :synopsis: SQLAlchemy persistence models.

.. py:module:: vaultspec_a2a.database.session
   :synopsis: Asynchronous database sessions.

.. py:module:: vaultspec_a2a.database.migrations
   :synopsis: Database schema migrations.

.. py:module:: vaultspec_a2a.database.artifact_repository
   :synopsis: Artifact persistence operations.

.. py:module:: vaultspec_a2a.database.authoring_cursor_repository
   :synopsis: Authoring cursor persistence operations.

.. py:module:: vaultspec_a2a.database.permission_repository
   :synopsis: Permission persistence operations.

.. py:module:: vaultspec_a2a.database.task_queue_repository
   :synopsis: Persisted task-queue operations.

.. py:module:: vaultspec_a2a.database.thread_repository
   :synopsis: Thread persistence operations.

Graph and context
~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.graph.nodes
   :synopsis: Executable graph nodes.

.. py:module:: vaultspec_a2a.graph.enums
   :synopsis: Graph execution enums.

.. py:module:: vaultspec_a2a.graph.events
   :synopsis: Graph-domain events.

.. py:module:: vaultspec_a2a.graph.protocols
   :synopsis: Graph integration protocols.

IPC and streaming
~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.ipc.schemas
   :synopsis: Gateway-worker message schemas.

.. py:module:: vaultspec_a2a.ipc.serializers
   :synopsis: Gateway-worker message serialization.

.. py:module:: vaultspec_a2a.streaming.types
   :synopsis: Streamed event and graph types.

Process lifecycle
~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.lifecycle.discovery
   :synopsis: Secret-free resident discovery and owner-restricted credential handoff.

``service.json`` carries a non-secret ``handoff_reference``. The referenced
adjacent ``service.token`` file carries the bearer credential and is validated
as an owner-restricted handoff before :func:`read_resident_service` returns it.

.. py:class:: DiscoveryState

.. py:class:: ServiceInfo

.. py:function:: service_json_path(a2a_home)

.. py:function:: read_resident_service(a2a_home)

.. py:function:: write_service_json(path, *, port, pid, service_token=None, now_ms=None)

.. py:module:: vaultspec_a2a.lifecycle.procs_config
   :synopsis: Development-process configuration.

.. py:module:: vaultspec_a2a.lifecycle.registration
   :synopsis: Development-process registration.

.. py:module:: vaultspec_a2a.lifecycle.registry
   :synopsis: Machine-global development-process registry.

.. py:module:: vaultspec_a2a.lifecycle.manager
   :synopsis: Development-process lifecycle operations.

.. py:module:: vaultspec_a2a.lifecycle.reconciliation
   :synopsis: Pure thread-recovery decisions after a gateway restart.

Team and telemetry
~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.team.team_config
   :synopsis: Team, agent, and topology configuration.

.. py:module:: vaultspec_a2a.telemetry.instrumentation
   :synopsis: OpenTelemetry and LangSmith setup.

.. py:module:: vaultspec_a2a.telemetry.middleware
   :synopsis: FastAPI and WebSocket instrumentation.

Thread and workspace support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:module:: vaultspec_a2a.thread.actor_tokens
   :synopsis: Bounded and redacted engine-provisioned per-role token bundles.

.. py:module:: vaultspec_a2a.thread.snapshots
   :synopsis: Thread snapshot projection.

.. py:module:: vaultspec_a2a.workspace.environment
   :synopsis: Workspace environment resolution.
