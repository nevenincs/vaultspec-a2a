"""Protect provider session ownership and deletion boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _production_sources() -> list[Path]:
    """List product sources without importing provider modules."""
    return [
        source
        for source in sorted(_PACKAGE_ROOT.rglob("*.py"))
        if "tests" not in source.relative_to(_PACKAGE_ROOT).parts
    ]


def test_no_production_caller_resumes_a_persisted_acp_session() -> None:
    """Provider sessions remain ephemeral unless resume ownership is added."""
    resuming: list[str] = []
    for source in _production_sources():
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "AcpChatModel"):
                continue
            if any(keyword.arg == "session_id" for keyword in node.keywords):
                relative = source.relative_to(_PACKAGE_ROOT)
                resuming.append(f"{relative.as_posix()}:{node.lineno}")

    assert not resuming, f"production callers resume persisted ACP sessions: {resuming}"


def _acp_lane_sources() -> list[Path]:
    """List every module the ACP chat lane is composed of.

    The lane is the chat model plus the private modules it delegates to, so a
    deletion call moved out of the model is still a deletion call the lane
    acquired. Naming the whole set keeps the boundary attached to the lane
    rather than to whichever file its code happens to live in today.
    """
    providers = _PACKAGE_ROOT / "providers"
    sources = [providers / "acp_chat_model.py", *sorted(providers.glob("_acp_*.py"))]
    assert len(sources) > 1, "the ACP lane module set went missing"
    return sources


def test_acp_lane_cannot_delete_the_operator_home() -> None:
    """The ACP lane cannot reclaim files in the operator's config home."""
    removers = {"rmtree", "unlink", "remove", "rmdir", "removedirs"}
    found = [
        f"{source.name}:{node.lineno} calls {node.func.attr}"
        for source in _acp_lane_sources()
        for node in ast.walk(
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        )
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in removers
    ]
    assert not found, f"ACP lane acquired filesystem deletion authority: {found}"
