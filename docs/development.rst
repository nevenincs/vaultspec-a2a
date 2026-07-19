Development setup
=================

This guide takes a contributor from a fresh clone to the repository's locked,
tracked-source-safe validation gates. Run every command from the repository
root.

Prerequisites and locked tooling
--------------------------------

Install these prerequisites:

* Git
* `Just 1.31 or later <https://just.systems/man/en/packages.html>`_
* `uv <https://docs.astral.sh/uv/getting-started/installation/>`_
* Python 3.13 or later; the project selects Python 3.13
* Docker, only for container workflows

Clone the repository and prepare its selected Python series:

.. code-block:: console

   git clone https://github.com/nevenincs/vaultspec-a2a
   cd vaultspec-a2a
   uv python install 3.13

Diagnose the host tools before synchronizing dependencies:

.. code-block:: console

   just doctor

``just doctor`` enforces Just 1.31 or later, requires ``uv``, and reports
Docker as optional. It doesn't validate Git, Python, dependencies, framework
enrollment, or application health.

Install the continuous integration (CI) contributor environment:

.. code-block:: console

   uv sync --locked --no-default-groups --extra server --group all

The ``base`` profile contains runtime dependencies. The ``tooling`` profile
supports hooks and narrower repository checks. The composed ``all`` group adds
documentation to tooling, while CI also selects the ``server`` extra. RAG and
Torch remain isolated in the optional ``rag`` extra. ``just dev deps all`` is
the explicit profile that selects every runtime extra.

Enroll Vaultspec Core and optional RAG
--------------------------------------

Enrollment reconciles repository integration files. It doesn't provision
external services, models, or Qdrant.

Enroll all Vaultspec Core (Core) provider projections in ``dev`` mode:

.. code-block:: console

   just dev vault setup

Core exclusively owns provider projections and its marker-bounded block in
``.gitignore``. Canonical inputs remain tracked, and content outside the marker
remains repository-owned.

Inspect the Core state and proposed changes before reconciling drift:

.. code-block:: console

   just dev vault status
   just dev vault doctor
   just dev vault install-dry-run
   just dev vault sync-dry-run

``status`` follows Core's diagnostic contract: exit code 0 means no findings,
1 means one or more warnings, and 2 means errors. Review the output and dry
runs; when their proposed changes are correct, reconcile through the owning
verb:

.. code-block:: console

   just dev vault sync

If semantic discovery is required, enroll the optional RAG bridge:

.. code-block:: console

   just dev rag setup

RAG is installed in ``dependency`` mode. Its profile already includes Model
Context Protocol (MCP) support. Enrollment doesn't download models or Qdrant,
and it doesn't rewrite Torch configuration. Diagnose it with:

.. code-block:: console

   just dev rag install-dry-run
   just dev rag status

Only explicit upgrade commands mutate the selected Core or RAG versions:

.. code-block:: console

   just dev vault upgrade
   just dev rag upgrade

Validate and diagnose
---------------------

Run the local validation sequence:

.. code-block:: console

   just ci

The command is fail-fast and runs these stages in order:

#. ``uv sync --locked --no-default-groups --extra server --group all`` prepares
   the exact locked environment.
#. ``just dev code check`` runs Ruff lint, Ruff format checking, Ty, and Deptry.
#. ``just dev test unit`` runs every test not marked ``service``.

A failed stage reports a validation failure. Later stages are *not run*.
Service tests and documentation are *excluded* from ``just ci``. The unit gate
does run non-service migration tests, but the hosted PostgreSQL upgrade and
downgrade round trip remains a separate workflow.

Use narrower commands to diagnose failures:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Command
     - Scope
   * - ``just dev code lint``
     - Run Ruff lint.
   * - ``just dev code format-check``
     - Check Ruff formatting without changing files.
   * - ``just dev code type``
     - Run the Ty type checker.
   * - ``just dev code dependencies``
     - Run the Deptry dependency checker.
   * - ``just dev test collect-unit``
     - Collect the non-service gate without executing it.
   * - ``just dev test unit``
     - Run every test not marked ``service``.
   * - ``just dev test service``
     - Deliberately run service-marked tests.
   * - ``just dev test all``
     - Deliberately run all collected tests.
   * - ``just dev build docs``
     - Run documentation tests, build HTML with Sphinx in nitpicky mode, and
       treat warnings as errors.

Hosted validation runs the documentation gate separately. Validation commands
don't intentionally modify tracked source, although tests and documentation
may create ignored caches or build output. ``just dev code repair`` explicitly
applies Ruff fixes and formatting; it doesn't repair Ty, Deptry, test, or
documentation findings.

Continue with :doc:`operations` for runtime commands and :doc:`architecture`
for ownership boundaries. Before proposing changes, read the `contribution
guide <https://github.com/nevenincs/vaultspec-a2a/blob/main/CONTRIBUTING.md>`_;
report suspected vulnerabilities through the `security policy
<https://github.com/nevenincs/vaultspec-a2a/blob/main/SECURITY.md>`_.
