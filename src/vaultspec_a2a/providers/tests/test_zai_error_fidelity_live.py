"""Live proof: what error discriminator the Z.ai lane actually puts on the wire.

Z.ai rides the Claude ACP adapter with a redirected base URL, so it is tempting
to assume it inherits the Claude lane's typed failures. It does not follow: the
adapter draws its ``errorKind`` from the CLI, and the CLI derives some kinds by
matching Anthropic's own English error prose, which an
Anthropic-compatible-but-different gateway need not reproduce. Whether a kind
survives on this lane is therefore a question about a running service, and the
only honest answer is an observed one.

This test provokes a REAL failure against the REAL Z.ai gateway through the real
adapter, and asserts on what comes back. The provocation is a deliberately
invalid bearer token, which is the cheapest reliable route to a status-gated
rejection and spends no model quota. No mock, no tape, no constructed payload:
if nothing is observed, nothing passes.

The observed kind is checked for membership in the vocabulary read from the
INSTALLED agent SDK type declaration rather than from a list written here, so a
gateway inventing its own kind is a failure rather than a silent pass.

Re-arm (one command, once a token exists):

    ZAI_AUTH_TOKEN=<glm-anthropic-gateway-token> \\
        uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/providers/tests/test_zai_error_fidelity_live.py

Service-marked, so deselected from the default suite. With no token configured
it SKIPS naming the missing prerequisite - an unarmed lane is reported as
unproven, never as proven.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...control.config import settings
from ...graph.enums import Model, Provider
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpError, AcpErrorCode, AcpPromptError
from ..factory import ProviderFactory
from ._installed_vocabulary import MissingInstalledVocabularyError, acp_error_kinds

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule


# A syntactically plausible bearer the gateway cannot have issued. Rejected at
# the gateway's authentication boundary before any model is engaged.
_REJECTED_TOKEN = "sk-vaultspec-probe-deliberately-invalid-credential"

# A rejected credential does NOT fail fast: the CLI treats an authentication
# status as retryable and exhausts its backoff schedule before surfacing the
# failure, which took just under four minutes when this probe was first driven.
# The bound sits well above that and well below the turn idle deadline, so a
# genuine hang fails the probe instead of parking it for ten minutes.
_PROBE_TIMEOUT_SECONDS = 480.0


@pytest.mark.service
@pytest.mark.asyncio
async def test_zai_rejected_credential_carries_a_typed_error_kind(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """A real Z.ai rejection arrives as a typed ``errorKind``, not as prose alone.

    The assertion that carries the verdict is that ``data.errorKind`` is present
    at all: the whole question about this lane is whether the discriminator
    survives a non-Anthropic gateway, and prose-only rejection is exactly the
    failure mode the governing decision gates this lane's typing on.
    """
    external_prerequisite("zai-credential")
    try:
        installed_kinds = acp_error_kinds()
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))

    model = ProviderFactory().create(
        Provider.ZAI, model=Model.LOW, workspace_root=tmp_path
    )
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("ANTHROPIC_BASE_URL") == settings.zai_base_url
    assert "ANTHROPIC_AUTH_TOKEN" in model.env_vars

    # Swap only the bearer, so everything else about the lane - command, backend,
    # gateway URL, session setup - stays the production path. ``env_vars`` is the
    # model's own declared field and ``model_post_init`` is what republishes it
    # into the frozen config the session reads, the same two steps
    # ``with_mcp_servers`` takes.
    rejected_env = dict(model.env_vars)
    rejected_env["ANTHROPIC_AUTH_TOKEN"] = _REJECTED_TOKEN
    rejected = model.model_copy(update={"env_vars": rejected_env})
    rejected.model_post_init(None)

    with pytest.raises(AcpError) as raised:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            async for _ in rejected.astream([HumanMessage(content="Say: pong")]):
                pass

    error = raised.value
    assert isinstance(error, AcpPromptError), (
        "a rejected credential must fail the prompt, not the transport; got "
        f"{type(error).__name__}: {error.message}"
    )
    assert error.code == AcpErrorCode.INTERNAL_ERROR, (
        "the adapter carries errorKind on its internal-error frame; a different "
        f"code means the kind rode a channel this lane does not read: {error.code}"
    )

    data = error.data
    assert isinstance(data, dict), (
        "Z.ai rejected the credential with no structured error data, so this "
        "lane carries no discriminator and its typing must degrade to unknown; "
        f"message was: {error.message}"
    )
    kind = data.get("errorKind")
    assert isinstance(kind, str) and kind, (
        "Z.ai rejected the credential without an errorKind, so this lane "
        "discriminates by prose alone; message was: " + error.message
    )
    assert kind in installed_kinds, (
        f"Z.ai returned errorKind {kind!r}, which the installed agent SDK does "
        f"not declare; the lane invents kinds and cannot be mapped as Claude is. "
        f"Installed vocabulary: {sorted(installed_kinds)}"
    )
    # The gateway answers a bad bearer with an authentication status, and the
    # CLI's status-gated branch turns that into this kind regardless of the
    # gateway's own prose. Pinning the value is what makes the result evidence
    # about fidelity rather than merely about shape.
    assert kind == "authentication_failed", (
        f"a rejected Z.ai credential typed as {kind!r} rather than "
        "'authentication_failed'; the status-gated derivation this lane's "
        "typing rests on no longer holds"
    )
