"""Frozen-binary entrypoint for the dashboard-bundled a2a runtime.

PyInstaller analyses and boots this script; it must stay minimal. The
``multiprocessing.freeze_support()`` call is the canonical Windows freeze
guard: a frozen child re-executes the binary, and without the guard any
multiprocessing use in the dependency closure would fork-bomb the entrypoint.
Everything else - argv dispatch, the service verbs, the run-module allowlist -
lives in the operator CLI, so source and frozen invocations share one code
path.
"""

import multiprocessing

from vaultspec_a2a.cli.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
