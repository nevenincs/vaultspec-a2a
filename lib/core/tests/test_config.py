import os
from pathlib import Path

from ...utils import Environment, LogLevel
from ..config import Settings


def test_config_default_values() -> None:
    settings = Settings()
    assert settings.environment == Environment.DEVELOPMENT
    assert settings.log_level == LogLevel.INFO
    assert settings.workspace_root == Path("./workspaces")


def test_config_vaultspec_env_prefix() -> None:
    # Save original state to preserve test purity
    orig_env = os.environ.get("VAULTSPEC_ENVIRONMENT")
    orig_level = os.environ.get("VAULTSPEC_LOG_LEVEL")
    orig_root = os.environ.get("VAULTSPEC_WORKSPACE_ROOT")

    try:
        test_path = str(Path("./test_workspace_override").absolute())
        os.environ["VAULTSPEC_ENVIRONMENT"] = "production"
        os.environ["VAULTSPEC_LOG_LEVEL"] = "error"
        os.environ["VAULTSPEC_WORKSPACE_ROOT"] = test_path

        # Initialize settings - it should automatically bind VAULTSPEC_ variables
        settings = Settings()
        assert settings.environment == Environment.PRODUCTION
        assert settings.log_level == LogLevel.ERROR
        assert settings.workspace_root == Path(test_path)
    finally:
        # Restore environment state
        if orig_env is not None:
            os.environ["VAULTSPEC_ENVIRONMENT"] = orig_env
        else:
            os.environ.pop("VAULTSPEC_ENVIRONMENT", None)

        if orig_level is not None:
            os.environ["VAULTSPEC_LOG_LEVEL"] = orig_level
        else:
            os.environ.pop("VAULTSPEC_LOG_LEVEL", None)

        if orig_root is not None:
            os.environ["VAULTSPEC_WORKSPACE_ROOT"] = orig_root
        else:
            os.environ.pop("VAULTSPEC_WORKSPACE_ROOT", None)
