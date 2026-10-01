"""The variables a2a declares to vaultspec-core, and which of them are credentials.

A workspace ``.env`` is repository content: it arrives with a clone, and a
service that read settings from it would let the repository it serves decide
which ports it binds, which database it opens and which endpoint it talks to.
vaultspec-core owns the one rule that keeps that shut - only a declared
credential is read from that file, one name at a time, and only when the
running interpreter belongs to the workspace and the workspace runs this
package as a project dependency. This module is the declaration side of that
rule: each credential a2a accepts is registered with core under this package's
name, so the gate that opens the file is resolved against a2a's own install
mode rather than another tool's.

Every name here is also a settings field, and the field's schema remains the
only declaration of what that name is spelled: the entries below are checked
against the field aliases, so a name added to the schema and forgotten here is
a failure rather than a credential quietly left ungated.

A credential never chains to a shared framework name, so each spelling a field
accepts is its own entry, canonical a2a name first and the owning tool's own
name behind it. The non-secret entry is the operator environment file itself -
a2a's replacement for reading settings out of the workspace, resolved through
the same accessor so that a blank value means unset here too.
"""

from typing import Final

from vaultspec_core.config import (
    ConfigVariable,
    VariableScope,
    register_registry,
)

from .env_prefix import ENV_PREFIX

__all__ = [
    "CREDENTIAL_VARIABLES",
    "ENV_FILE_VARIABLE",
]

#: The distribution name whose install mode gates the workspace ``.env``.
PACKAGE: Final = "vaultspec-a2a"


def _credential(env_name: str, description: str) -> ConfigVariable:
    """Declare one credential name, eligible for the gated workspace ``.env``."""
    return ConfigVariable(
        env_name=env_name,
        attr_name=None,
        var_type=str,
        default=None,
        description=description,
        secret=True,
        scope=(
            VariableScope.PRODUCT
            if env_name.startswith(ENV_PREFIX)
            else VariableScope.EXTERNAL
        ),
        workspace_dotenv=True,
    )


def _names(
    suffix: str, foreign: tuple[str, ...], description: str
) -> tuple[ConfigVariable, ...]:
    """Declare a credential's a2a name and the foreign spellings behind it."""
    return (
        _credential(f"{ENV_PREFIX}{suffix}", description),
        *(_credential(name, description) for name in foreign),
    )


#: The operator's own settings file. Not repository content and not discovered:
#: it supplies settings only because the operator named it on this process, so
#: it ranks with the session environment rather than with the workspace.
ENV_FILE_VARIABLE: Final = ConfigVariable(
    env_name=f"{ENV_PREFIX}ENV_FILE",
    attr_name=None,
    var_type=str,
    default=None,
    description=(
        "Path to the operator's settings file for this service. Relative to "
        "the project root; a named file that does not exist is refused."
    ),
)

#: Every settings field a workspace ``.env`` may supply, mapped to the names it
#: is accepted under, canonical first. A field absent from this mapping is a
#: setting, and the workspace never supplies it.
CREDENTIAL_VARIABLES: Final[dict[str, tuple[ConfigVariable, ...]]] = {
    "openai_api_key": _names(
        "OPENAI_API_KEY", ("OPENAI_API_KEY",), "API key for the OpenAI lane."
    ),
    "zhipu_api_key": _names(
        "ZHIPU_API_KEY", ("ZHIPU_API_KEY",), "API key for the Zhipu lane."
    ),
    "zai_auth_token": _names(
        "ZAI_AUTH_TOKEN",
        ("ZAI_AUTH_TOKEN", "ZAI_API_KEY"),
        "Auth token for the Z.ai Anthropic-compatible lane.",
    ),
    "kimi_model_api_key": _names(
        "KIMI_MODEL_API_KEY",
        ("KIMI_MODEL_API_KEY",),
        "API key in a complete temporary Kimi model definition.",
    ),
    "internal_token": _names("INTERNAL_TOKEN", (), "Bearer for gateway<->worker IPC."),
    "gateway_service_token": _names(
        "GATEWAY_TOKEN", (), "Bearer an attaching engine presents to the gateway."
    ),
}


register_registry(
    PACKAGE,
    (
        ENV_FILE_VARIABLE,
        *(entry for entries in CREDENTIAL_VARIABLES.values() for entry in entries),
    ),
)
