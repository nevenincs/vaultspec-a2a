"""Unit tests for security-critical ACP RPC handler paths.

Tests sandbox path validation and terminal creation security without
requiring a live ACP subprocess.
"""

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest

from .._acp_rpc_handlers import (
    _ENV_NAME_RE,
    _SHELL_METACHAR_RE,
    _TERMINAL_COMMAND_ALLOWLIST,
    on_terminal_create,
    sandbox_path,
)
from .._acp_types import _AcpModelConfig, _AcpSessionContext


def _make_config(workspace_root: str | None = None) -> _AcpModelConfig:
    """Create a minimal _AcpModelConfig for security tests."""
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        cwd=None,
        command=["echo"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


# ---------------------------------------------------------------------------
# sandbox_path — path traversal prevention
# ---------------------------------------------------------------------------


class TestSandboxPath:
    """Tests for sandbox_path() path traversal prevention."""

    def test_allows_relative_path_within_root(self, tmp_path: Path) -> None:
        """A path within the workspace root resolves correctly."""
        config = _make_config(workspace_root=str(tmp_path))
        result = sandbox_path("subdir/file.txt", config)
        assert result == (tmp_path / "subdir" / "file.txt").resolve()

    def test_allows_nested_path(self, tmp_path: Path) -> None:
        """Deeply nested paths within the workspace root are allowed."""
        config = _make_config(workspace_root=str(tmp_path))
        result = sandbox_path("a/b/c/d.txt", config)
        assert result.is_relative_to(tmp_path.resolve())

    def test_blocks_dotdot_traversal(self, tmp_path: Path) -> None:
        """Path traversal via '../' is rejected."""
        config = _make_config(workspace_root=str(tmp_path))
        with pytest.raises(ValueError, match="escapes sandbox"):
            sandbox_path("../escape.txt", config)

    def test_blocks_deeply_nested_traversal(self, tmp_path: Path) -> None:
        """Multi-level '../../../' traversal is rejected."""
        config = _make_config(workspace_root=str(tmp_path))
        with pytest.raises(ValueError, match="escapes sandbox"):
            sandbox_path("subdir/../../../../../../etc/passwd", config)

    def test_allows_absolute_path_within_root(self, tmp_path: Path) -> None:
        """Absolute paths within the sandbox root are allowed."""
        config = _make_config(workspace_root=str(tmp_path))
        inner = str(tmp_path / "a.txt")
        result = sandbox_path(inner, config)
        assert result == Path(inner).resolve()

    def test_blocks_absolute_path_outside_root(self, tmp_path: Path) -> None:
        """Absolute paths outside the sandbox root are rejected."""
        config = _make_config(workspace_root=str(tmp_path))
        with pytest.raises(ValueError, match="escapes sandbox"):
            sandbox_path("/etc/passwd", config)

    def test_blocks_windows_drive_escape(self, tmp_path: Path) -> None:
        """Windows drive-relative path that escapes sandbox is rejected."""
        config = _make_config(workspace_root=str(tmp_path))
        # On any platform, a path that resolves outside tmp_path must be rejected
        with pytest.raises(ValueError, match="escapes sandbox"):
            sandbox_path("/windows/system32/cmd.exe", config)


# ---------------------------------------------------------------------------
# _TERMINAL_COMMAND_ALLOWLIST — allowlist validation
# ---------------------------------------------------------------------------


class TestTerminalCommandAllowlist:
    """Tests for the terminal command allowlist."""

    def test_python_is_allowed(self) -> None:
        assert "python" in _TERMINAL_COMMAND_ALLOWLIST

    def test_git_is_allowed(self) -> None:
        assert "git" in _TERMINAL_COMMAND_ALLOWLIST

    def test_npm_is_allowed(self) -> None:
        assert "npm" in _TERMINAL_COMMAND_ALLOWLIST

    def test_curl_is_not_allowed(self) -> None:
        assert "curl" not in _TERMINAL_COMMAND_ALLOWLIST

    def test_rm_is_not_allowed(self) -> None:
        assert "rm" not in _TERMINAL_COMMAND_ALLOWLIST

    def test_wget_is_not_allowed(self) -> None:
        assert "wget" not in _TERMINAL_COMMAND_ALLOWLIST

    def test_nc_is_not_allowed(self) -> None:
        """netcat / nc must not be in the allowlist (exfiltration risk)."""
        assert "nc" not in _TERMINAL_COMMAND_ALLOWLIST
        assert "netcat" not in _TERMINAL_COMMAND_ALLOWLIST


# ---------------------------------------------------------------------------
# _SHELL_METACHAR_RE — shell metacharacter detection
# ---------------------------------------------------------------------------


class TestShellMetacharPattern:
    """Tests for the shell metacharacter rejection pattern."""

    @pytest.mark.parametrize(
        "token",
        [
            "cmd|malicious",
            "arg; rm -rf /",
            "$(evil)",
            "`backtick`",
            "arg>file",
            "arg<file",
            "arg&background",
        ],
    )
    def test_detects_metachar(self, token: str) -> None:
        """Shell metacharacters are detected correctly."""
        assert _SHELL_METACHAR_RE.search(token) is not None

    @pytest.mark.parametrize(
        "token",
        [
            "python",
            "git",
            "pytest",
            "/usr/bin/python3.13",
            "C:\\Python313\\python.exe",
            "--flag=value",
            "path/to/script.py",
        ],
    )
    def test_allows_safe_tokens(self, token: str) -> None:
        """Safe command tokens pass the metachar check."""
        assert _SHELL_METACHAR_RE.search(token) is None


# ---------------------------------------------------------------------------
# _ENV_NAME_RE — environment variable name validation
# ---------------------------------------------------------------------------


class TestEnvNamePattern:
    """Tests for the env variable name validation pattern."""

    @pytest.mark.parametrize(
        "name",
        ["MY_VAR", "PATH", "_UNDERSCORE", "VAR123", "a", "_"],
    )
    def test_valid_names_match(self, name: str) -> None:
        """Valid POSIX env var names pass the pattern."""
        assert _ENV_NAME_RE.match(name) is not None

    @pytest.mark.parametrize(
        "name",
        ["1STARTS_WITH_DIGIT", "has space", "has-dash", "has.dot", "", "has=equals"],
    )
    def test_invalid_names_rejected(self, name: str) -> None:
        """Invalid env var names are rejected by the pattern."""
        assert _ENV_NAME_RE.match(name) is None


# ---------------------------------------------------------------------------
# on_terminal_create — allowlist and metachar rejection (unit-level)
# ---------------------------------------------------------------------------


class TestOnTerminalCreateValidation:
    """Tests for the security validation in on_terminal_create().

    These tests call on_terminal_create directly with a minimal session
    context to test the input validation paths without spawning a real
    subprocess.
    """

    def _make_ctx(self) -> object:
        """Create a minimal session context for on_terminal_create calls.

        Policy exception: _MinimalSessionContext satisfies the structural
        subset of _AcpSessionContext used by on_terminal_create's validation
        paths (allowlist check, metachar check, sandbox check). This is pure
        logic that runs before any subprocess is spawned. The project's
        no-mocks mandate targets mocking out network/LLM/subprocess calls;
        this helper tests pure validation logic.
        """

        class _MinimalSessionContext:
            stdin_lock = asyncio.Lock()
            terminals: ClassVar[dict] = {}

        # Structural guard: verify real type has the attrs we shadow
        _ctx_fields = {f.name for f in dataclasses.fields(_AcpSessionContext)}
        assert "stdin_lock" in _ctx_fields, "ctx interface drift"
        assert "terminals" in _ctx_fields, "ctx interface drift"

        return _MinimalSessionContext()

    @pytest.mark.asyncio
    async def test_rejects_command_not_in_allowlist(self, tmp_path: Path) -> None:
        """Commands not in the allowlist return an error response."""
        config = _make_config(workspace_root=str(tmp_path))
        ctx = self._make_ctx()
        resp = await on_terminal_create(
            rpc_id=1,
            params={"command": "curl", "args": ["http://example.com"]},
            ctx=cast("Any", ctx),
            config=config,
        )
        resp_dict = cast("dict[str, Any]", resp)
        assert "error" in resp_dict
        error_obj = cast("dict[str, Any]", resp_dict["error"])
        assert error_obj["code"] == -32603
        assert "allowlist" in error_obj["message"]

    @pytest.mark.asyncio
    async def test_rejects_metachar_in_command(self, tmp_path: Path) -> None:
        """Commands with shell metacharacters return an error response."""
        config = _make_config(workspace_root=str(tmp_path))
        ctx = self._make_ctx()
        resp = await on_terminal_create(
            rpc_id=1,
            params={"command": "python", "args": ["script.py; rm -rf /"]},
            ctx=cast("Any", ctx),
            config=config,
        )
        resp_dict = cast("dict[str, Any]", resp)
        assert "error" in resp_dict
        error_obj = cast("dict[str, Any]", resp_dict["error"])
        assert error_obj["code"] == -32603
        assert "metacharacter" in error_obj["message"]

    @pytest.mark.asyncio
    async def test_rejects_cwd_outside_sandbox(self, tmp_path: Path) -> None:
        """A cwd outside the workspace root returns an error response."""
        config = _make_config(workspace_root=str(tmp_path))
        ctx = self._make_ctx()
        resp = await on_terminal_create(
            rpc_id=1,
            params={"command": "python", "args": [], "cwd": "/etc"},
            ctx=cast("Any", ctx),
            config=config,
        )
        resp_dict = cast("dict[str, Any]", resp)
        assert "error" in resp_dict
        error_obj = cast("dict[str, Any]", resp_dict["error"])
        assert error_obj["code"] == -32603
        assert "sandbox" in error_obj["message"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_env_var_name(self, tmp_path: Path) -> None:
        """Invalid env variable names return an error response."""
        config = _make_config(workspace_root=str(tmp_path))
        ctx = self._make_ctx()
        resp = await on_terminal_create(
            rpc_id=1,
            params={
                "command": "python",
                "args": [],
                "env": [{"name": "1INVALID", "value": "x"}],
            },
            ctx=cast("Any", ctx),
            config=config,
        )
        resp_dict = cast("dict[str, Any]", resp)
        assert "error" in resp_dict
        error_obj = cast("dict[str, Any]", resp_dict["error"])
        assert error_obj["code"] == -32603
        assert "Invalid environment variable" in error_obj["message"]
