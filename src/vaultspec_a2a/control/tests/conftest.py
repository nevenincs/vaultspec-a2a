"""Test configuration for control-plane tests."""

import importlib

# Warm the graph package before any control test module imports
# ``control.thread_service``. That module imports ``context.metadata`` first,
# which triggers a latent ``context -> thread -> graph -> nodes -> supervisor ->
# context`` import cycle when it is the first vaultspec import in a fresh
# interpreter; importing ``graph`` up front resolves ``context.token_budget``
# fully so the later import finds it cached. (Source-level fix for the cycle is
# graph-domain work tracked outside this test package.)
importlib.import_module("vaultspec_a2a.graph")
