Python module reference
=======================

This reference documents the supported public APIs and their runtime ownership
boundaries. Import concrete features from the module that owns them.

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

.. py:function:: create_app(lifespan=None)

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
   :synopsis: HTTP and WebSocket wire schemas.

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

.. py:module:: vaultspec_a2a.control.verdict_subscriber
   :synopsis: Authoring verdict delivery.

Persistence
~~~~~~~~~~~

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

.. py:module:: vaultspec_a2a.thread.snapshots
   :synopsis: Thread snapshot projection.

.. py:module:: vaultspec_a2a.workspace.environment
   :synopsis: Workspace environment resolution.
