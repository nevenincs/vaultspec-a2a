Glossary
========

.. glossary::
   :sorted:

   agent harness
      The repository tooling that prepares an agent for project workflows. It
      includes Vaultspec Core (Core), retrieval-augmented generation (RAG),
      skills, personas, rules, templates, command-line tools, Model Context
      Protocol (MCP) support, and provider projections.

   canonical Vaultspec input
      A tracked source from which Core derives provider projections and other
      managed artifacts.

   dependency profile
      An explicit dependency selection. ``base`` contains runtime dependencies;
      ``server`` adds server integrations; ``rag`` adds semantic discovery;
      ``tooling`` supports repository validation; ``all`` selects every runtime
      extra plus documentation and tooling groups.

   enrollment
      Reconciliation of repository integration artifacts for an existing
      workspace. Enrollment doesn't acquire external runtime resources.

   provisioning
      Preparation of a workspace or runtime resource. Workspace provisioning
      wraps Core installation, synchronization, and verification; external
      RAG provisioning acquires resources such as models or Qdrant.

   foreground process
      An attached process whose lifetime and interruption belong to the caller.

   gateway
      The request-facing Hypertext Transfer Protocol (HTTP) and WebSocket edge.

   worker
      The separate process that executes graphs delegated through the gateway.

   engine
      A named authoring-side process that consumes the gateway edge and works
      against an explicit repository and workspace seat.

   authoring plane
      The engine-facing side that turns agent output into reviewable proposals.

   Just facade
      The discoverable, lock-backed repository command surface. It routes work
      to an owner without implementing product or lifecycle logic.

   managed block
      A marker-bounded portion of a mixed-ownership file that Core may rewrite.
      Content outside the markers remains repository-owned.

   named host process
      A gateway, worker, or engine addressed through a stable registry name
      rather than only an operating-system process identifier.

   process registry
      The machine-global owner of named host-process allocation, registration,
      liveness, restart state, and tree termination.

   product CLI
      The ``vaultspec-a2a`` command surface that owns product behavior.

   project-locked tool
      A tool version selected by committed project lock state instead of an
      ambient or global ``latest`` installation.

   provider projection
      A provider-specific configuration or instruction artifact that Core
      derives from canonical Vaultspec inputs. It is managed output rather than
      an independent source of truth and should not be edited by hand.

   repair
      An explicit mutation that corrects source or managed-state drift without
      selecting a newer dependency version.

   stack
      A Docker Compose (Compose)-owned project that manages one or more related
      services as a bounded lifecycle unit.

   Vaultspec sync
      The explicit Core operation that compares canonical inputs with managed
      provider projections, then applies bounded reconciliation.

   reconciliation
      Comparison of declared and observed managed state. The owning tool may
      report drift or, through an explicit mutating command, converge it.

   validation
      Verification that reports contract or state drift without intentionally
      modifying tracked source. A validation command may still create ignored
      caches, logs, or build output.

   upgrade
      A deliberate dependency-selection change followed by lock and convergence
      checks.

See :doc:`development`, :doc:`operations`, and :doc:`architecture` for these
terms in context. The `contribution guide
<https://github.com/nevenincs/vaultspec-a2a/blob/main/CONTRIBUTING.md>`_ defines
change-submission policy; the `security policy
<https://github.com/nevenincs/vaultspec-a2a/blob/main/SECURITY.md>`_ defines how
to report vulnerabilities.
