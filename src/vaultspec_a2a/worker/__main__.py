"""Allow running the worker as ``python -m vaultspec_a2a.worker``."""

from .app import main

__all__: list[str] = []

if __name__ == "__main__":
    main()
