"""Shared fixtures for evaluation suites.

Provides LangSmith client and dataset reference helpers used across
all evaluation dimensions.
"""

from __future__ import annotations

import os

from langsmith import Client


def get_langsmith_client() -> Client:
    """Return a configured LangSmith client.

    Reads ``LANGSMITH_API_KEY`` from environment. Raises if not set.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        msg = "LANGSMITH_API_KEY must be set to run evaluations"
        raise RuntimeError(msg)
    return Client(api_key=api_key)
