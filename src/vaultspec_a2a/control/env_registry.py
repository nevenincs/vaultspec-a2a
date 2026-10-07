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
name behind it. The non-secret entries are the operator environment file itself -
a2a's replacement for reading settings out of the workspace, resolved through
the same accessor so that a blank value means unset here too - and the lane
plugins setting, declared so the registry records that a workspace can never
supply the modules a process imports.

The provider names a2a never registers are declared here too. With the
registered credentials they are the whole provider-credential vocabulary, so
the provider-child scrub and the development credential scopes read one list
rather than each keeping a copy that drifts.
"""

from typing import Final

from vaultspec_core.config import (
    ConfigVariable,
    VariableScope,
    register_registry,
)

from .env_prefix import ENV_PREFIX

__all__ = [
    "CREDENTIAL_ENV_NAMES",
    "CREDENTIAL_VARIABLES",
    "ENV_FILE_VARIABLE",
    "FOREIGN_PROVIDER_ENV_NAMES",
    "LANE_PLUGINS_VARIABLE",
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

#: The modules whose in-process lanes a process imports. A setting, never a
#: credential: neither a workspace ``.env`` nor the project store may supply it,
#: so it reaches a process only through the environment its launcher hands it.
LANE_PLUGINS_VARIABLE: Final = ConfigVariable(
    env_name=f"{ENV_PREFIX}LANE_PLUGINS",
    attr_name=None,
    var_type=str,
    default=None,
    description=(
        "Comma-separated module paths, each exposing register_lanes(registry). "
        "Honoured only while the in-process lanes are armed outside the desktop "
        "profile; any other non-empty value refuses startup."
    ),
)

#: Every settings field a workspace ``.env`` may supply, mapped to the names it
#: is accepted under, canonical first. A field absent from this mapping is a
#: setting, and the workspace never supplies it.
CREDENTIAL_VARIABLES: Final[dict[str, tuple[ConfigVariable, ...]]] = {
    "claude_code_oauth_token": _names(
        "CLAUDE_CODE_OAUTH_TOKEN",
        ("CLAUDE_CODE_OAUTH_TOKEN",),
        "Headless OAuth token for the declared Claude oauth_token channel.",
    ),
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

#: Every name a credential is accepted under, a2a's own spellings and the
#: owning tools' alike.
CREDENTIAL_ENV_NAMES: Final[frozenset[str]] = frozenset(
    entry.env_name for entries in CREDENTIAL_VARIABLES.values() for entry in entries
)

#: Provider names a2a never accepts a credential under, which an operator's
#: environment may still carry for another tool. None is registered, so the
#: workspace ``.env`` never supplies one, and every one is denied to a provider
#: child: a lane's auth reaches it only when the provider layer injects it.
FOREIGN_PROVIDER_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_LOG",
        "ZAI_BASE_URL",
        "ZAI_ANTHROPIC_BASE_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_OPENAI_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_TRACING_V2",
        # Kimi Code's temporary-provider definition is an all-or-none unit.
        # The rest of its current family and its retired spellings are denied
        # with the registered key, so only the Settings-owned current
        # definition can be re-injected by the factory.
        "KIMI_API_KEY",
        "KIMI_BASE_URL",
        "KIMI_MODEL_BASE_URL",
        "KIMI_MODEL_NAME",
        "KIMI_MODEL_MAX_CONTEXT_SIZE",
        "KIMI_MODEL_CAPABILITIES",
    }
)


register_registry(
    PACKAGE,
    (
        ENV_FILE_VARIABLE,
        LANE_PLUGINS_VARIABLE,
        *(entry for entries in CREDENTIAL_VARIABLES.values() for entry in entries),
    ),
)
