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
* `Node.js <https://nodejs.org/>`_ with npm for Claude and Z.ai ACP workflows;
  ``.node-version`` selects the required version
* Docker, only for container workflows

Clone the repository and prepare its selected Python series:

.. code-block:: console

   git clone https://github.com/nevenincs/vaultspec-a2a
   cd vaultspec-a2a
   uv python install 3.13

Diagnose the host tools before synchronizing dependencies:

.. code-block:: console

   just doctor-check

``just doctor-check`` enforces Just 1.31 or later, requires ``uv``, and reports
Docker as optional. ``just doctor-node`` checks the pinned Node and npm runtime.
It doesn't validate Git, Python,
dependencies, framework enrollment, or application health.

Install the continuous integration (CI) contributor environment:

.. code-block:: console

   just init

For Claude or Z.ai ACP work, run ``just init-full`` instead. It restores the
Node dependency graph as well as the Python environment and tooling.

The ``base`` profile contains runtime dependencies. The ``tooling`` profile
supports hooks and narrower repository checks. The composed ``all`` group adds
documentation to tooling, while CI also selects the ``otlp`` extra. RAG and
Torch remain isolated in the optional ``rag`` extra. ``just deps-all`` is
the explicit profile that selects every runtime extra. The separate Node recipe
restores the exact Claude ACP dependency graph from ``package-lock.json``.

Enroll Vaultspec Core and optional RAG
--------------------------------------

Enrollment reconciles repository integration files. It doesn't provision
external services, models, or Qdrant.

Enroll all Vaultspec Core (Core) provider projections in ``dev`` mode:

.. code-block:: console

   just vault-setup

Core exclusively owns provider projections and its marker-bounded block in
``.gitignore``. Canonical inputs remain tracked, and content outside the marker
remains repository-owned.

Inspect the Core state and proposed changes before reconciling drift:

.. code-block:: console

   just vault-status
   just vault-doctor
   just vault-install-dry-run
   just vault-sync-dry-run

``status`` follows Core's diagnostic contract: exit code 0 means no findings,
1 means one or more warnings, and 2 means errors. Review the output and dry
runs; when their proposed changes are correct, reconcile through the owning
verb:

.. code-block:: console

   just vault-sync

If semantic discovery is required, enroll the optional RAG bridge:

.. code-block:: console

   just rag-setup

RAG is installed in ``dependency`` mode. Its profile already includes Model
Context Protocol (MCP) support. Enrollment doesn't download models or Qdrant,
and it doesn't rewrite Torch configuration. Diagnose it with:

.. code-block:: console

   just rag-install-dry-run
   just rag-status

Only explicit upgrade commands mutate the Core or RAG lock selection:

.. code-block:: console

   just vault-upgrade
   just rag-upgrade

Core adoption stages forced reconciliation in a disposable clone. It promotes
runtime state only when the tracked projection is byte-identical, then performs
a non-destructive live sync. RAG upgrades resolve the exact ACP runtime
requirement in ``src/vaultspec_a2a/providers/_acp_mcp.py``. Change that reviewed
authority first when selecting a new RAG release; the upgrade command then
converges the lock, installed CLI, enrollment, and status to it.

Validate and diagnose
---------------------

Run the local validation sequence:

.. code-block:: console

   just ci

The command is fail-fast and runs these stages in order:

#. ``uv sync --locked --no-default-groups --extra otlp --group all`` prepares
   the exact locked environment.
#. ``just deps-node`` restores the pinned Claude ACP runtime.
#. ``just check-all`` runs Ruff lint, Ruff format checking, Ty, Deptry,
   and Actionlint workflow validation.
#. ``just test-unit`` runs every test not marked ``service``.

A failed stage reports a validation failure. Later stages are *not run*.
Service tests and documentation are *excluded* from ``just ci``. The unit gate
does run non-service migration tests, but the hosted SQLite upgrade and
downgrade round trip remains a separate workflow.

Use narrower commands to diagnose failures:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Command
     - Scope
   * - ``just check-python``
     - Run Ruff lint and format verification.
   * - ``just check-type``
     - Run the Ty type checker.
   * - ``just check-dependencies``
     - Run the Deptry dependency checker.
   * - ``just check-all``
     - Run every gating dimension that holds the line today.
   * - ``just test-collect-unit``
     - Collect the non-service gate without executing it.
   * - ``just test-unit``
     - Run every test not marked ``service``.
   * - ``just test-service``
     - Deliberately run service-marked tests.
   * - ``just test-all``
     - Deliberately run all collected tests.
   * - ``just docs-build``
     - Run documentation tests, build HTML with Sphinx in nitpicky mode, and
       treat warnings as errors.

Hosted validation runs the documentation gate separately. Validation commands
don't intentionally modify tracked source, although tests and documentation
may create ignored caches or build output. ``just fix-python`` explicitly
applies Ruff fixes and formatting; it doesn't repair Ty, Deptry, test, or
documentation findings.

Regenerate the published OpenAPI contract
-----------------------------------------

The repository-root ``openapi.json`` is the published Hypertext Transfer
Protocol (HTTP) contract, and the unit gate binds it to the application it
documents. ``src/vaultspec_a2a/api/tests/test_openapi_artifact.py`` asserts that
the committed file is valid UTF-8 JavaScript Object Notation (JSON), documents
every served path and no unserved one, reports the running version, carries no
development-record identifiers, and matches ``create_app().openapi()`` field for
field.

Any change to a route, request model, response model, or security declaration
therefore fails that test until the artifact is regenerated. The test module is
its own regeneration script, and this is the only supported way to rewrite the
file:

.. code-block:: console

   uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact

Don't hand-edit ``openapi.json``. It's generated output, and the exact-match
assertion will reject any edit that the application doesn't itself produce.

Cut a release
-------------

Write conventional commit subjects such as ``feat:``, ``fix:``, and ``feat!:``.
release-please keeps a release pull request open with the next version and the
changelog it derives, and rebuilds that branch on ``main``'s newest head after
every commit that lands. That path releases nothing, and merging the pull
request by hand doesn't release it either.

To release, dispatch the **Release Please** workflow. Its cut:

#. Finds the pending release pull request and refuses a candidate that is behind
   ``main`` or ambiguous.
#. Proves that pull request's exact head with the full merge gate. A release tag
   can't be deleted, so the proof comes first: a release commit that failed its
   gate after being tagged would be a permanent tag of a commit nobody can ship.
#. Squash-merges only that head, then refuses the merge if the landed tree isn't
   the proven one.
#. Has release-please force the tag into existence and create an unpublished
   draft release, seconds after the merge.
#. Dispatches **Release** with that tag.

The tag has to follow the merge with nothing in between. The default workflow
token never holds the ``workflows`` permission, and without it GitHub refuses any
tag or release targeting a commit whose ``.github/workflows`` differ from the
branch head. A workflow change landing between a release commit's merge and its
tag therefore leaves the release untaggable by every later run.

**Release** then freezes every declared target natively, proves each frozen
artifact starts, serves, and stops, attaches the archives and their ``.sha256``
sidecars to the draft, attests and verifies their provenance, and publishes the
draft as its last step. A visible release therefore carries everything it claims
to, and a failure anywhere in the lane leaves a draft nobody has been shown.
Fix the cause and dispatch **Release** again for the same tag.

Recover a release this token can't tag
--------------------------------------

A cut can stop in ``Create the release for the merged proposal`` with ``Resource
not accessible by integration``. Its ``Name a release this token cannot tag``
step then names the tag and the workflow files that block it. This happens when
a workflow change lands between the release commit's merge and its tag, as when
a release pull request merged by hand waits for a cut. No rerun and no later cut
can finish it.

Finish it with your own credentials, as the cut would have. Relabel the pull
request first, so the next cut doesn't pick it up again:

.. code-block:: console

   REPO=nevenincs/vaultspec-a2a
   PR=<release pull request number>
   VERSION=<version>
   TAG="v$VERSION"
   SHA=$(gh pr view "$PR" --repo "$REPO" --json mergeCommit --jq .mergeCommit.oid)

   gh pr edit "$PR" --repo "$REPO" \
     --remove-label "autorelease: pending" --add-label "autorelease: tagged"
   git fetch origin "$SHA"
   git push origin "$SHA:refs/tags/$TAG"
   git show "$SHA:CHANGELOG.md" \
     | awk -v h="## [$VERSION]" 'index($0, "## [") == 1 { p = index($0, h) == 1 } p' \
     > release-notes.md
   gh release create "$TAG" --repo "$REPO" --verify-tag --draft \
     --title "vaultspec-a2a v$VERSION" --notes-file release-notes.md
   gh workflow run release.yml --repo "$REPO" --ref main -f tag="$TAG"

``--draft`` is required: the lane publishes the release itself once every archive
is attached and verified. ``--verify-tag`` refuses to invent a tag, so the push
above has to have succeeded. The ``awk`` filter takes the one changelog section
for this version from the release commit's own ``CHANGELOG.md``.

Continue with :doc:`operations` for runtime commands and :doc:`architecture`
for ownership boundaries. Before proposing changes, read the `contribution
guide <https://github.com/nevenincs/vaultspec-a2a/blob/main/CONTRIBUTING.md>`_;
report suspected vulnerabilities through the `security policy
<https://github.com/nevenincs/vaultspec-a2a/blob/main/SECURITY.md>`_.
