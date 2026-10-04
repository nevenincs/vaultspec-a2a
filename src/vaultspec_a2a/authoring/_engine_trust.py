"""Filesystem provenance and proof of possession for engine discovery."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from ..desktop._filesystem_authority import (
    assert_directory_authority,
    directory_lease,
    open_shared_read_descriptor,
    path_is_link_like,
    resolve_directory_authority,
)
from ..desktop._platform_acl import (
    confirm_opened_secret,
    credential_file_is_owner_restricted,
    path_is_owner_restricted,
    unfollowed_read_flags,
)
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

ENGINE_RECORD_VERSION = 1
ENGINE_PRODUCER = "vaultspec-engine"
CHALLENGE_HEADER = "x-vaultspec-engine-challenge"
PROOF_HEADER = "x-vaultspec-engine-proof"
_MAX_RECORD_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class TrustedEngineRecord:
    """Identity read from protected state, never from repository content."""

    port: int
    pid: int
    started_ms: int
    bearer_token: str = field(repr=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def proof_message(self, challenge: str) -> bytes:
        """Bind a fresh challenge to this producer's recorded lifecycle."""
        return (
            f"{ENGINE_PRODUCER}:{ENGINE_RECORD_VERSION}\n"
            f"{self.port}\n{self.pid}\n{self.started_ms}\n{challenge}"
        ).encode("ascii")


def _record_path_is_external(path: Path, workspace_roots: tuple[Path, ...]) -> bool:
    if not path.is_absolute():
        return False
    # Reject aliases before canonicalizing: resolving first would erase the
    # evidence that repository-controlled content redirected the read.
    if any(path_is_link_like(item) for item in (path, *path.parents)):
        return False
    canonical = path.resolve(strict=True)
    if any(canonical.is_relative_to(root.resolve()) for root in workspace_roots):
        return False
    return not any((parent / ".git").exists() for parent in canonical.parents)


def _read_private_record(path: Path) -> dict[str, object] | None:
    authority = resolve_directory_authority(path.parent)
    if not path_is_owner_restricted(authority.path):
        return None
    with directory_lease(authority) as leased:
        if not credential_file_is_owner_restricted(path):
            return None
        named = path.stat(follow_symlinks=False)
        if os.name == "posix":
            descriptor = os.open(
                path.name,
                unfollowed_read_flags() | os.O_NONBLOCK,
                dir_fd=leased.dir_fd,
            )
        else:
            descriptor = open_shared_read_descriptor(path)
        try:
            if not confirm_opened_secret(descriptor, named=named, path=path):
                return None
            opened = os.fstat(descriptor)
            if opened.st_nlink != 1 or opened.st_size > _MAX_RECORD_BYTES:
                return None
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                contents = handle.read(_MAX_RECORD_BYTES + 1)
            assert_directory_authority(leased)
            if len(contents) > _MAX_RECORD_BYTES:
                return None
            decoded: object = json.loads(contents)
            return coerce_object_mapping(decoded)
        finally:
            if descriptor != -1:
                os.close(descriptor)


def _positive_int(info: Mapping[str, object], name: str) -> int | None:
    value = info.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _parse_engine_identity(info: Mapping[str, object]) -> TrustedEngineRecord | None:
    version = info.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != ENGINE_RECORD_VERSION
        or info.get("producer") != ENGINE_PRODUCER
    ):
        return None
    port = _positive_int(info, "port")
    pid = _positive_int(info, "pid")
    started_ms = _positive_int(info, "started_ms")
    token = info.get("service_token")
    if (
        port is None
        or port > 65_535
        or pid is None
        or started_ms is None
        or not isinstance(token, str)
        or not token.isascii()
        or len(token) < 32
        or len(token) > 4096
        or any(not 33 <= ord(character) <= 126 for character in token)
    ):
        return None
    return TrustedEngineRecord(port, pid, started_ms, token)


def read_engine_record(
    path: Path, *, workspace_roots: tuple[Path, ...], now_ms: int
) -> TrustedEngineRecord | None:
    """Read a bounded, private engine identity; unsafe candidates are unavailable."""
    from .discovery import heartbeat_is_fresh

    try:
        if not _record_path_is_external(path, workspace_roots):
            return None
        info = _read_private_record(path)
        if info is None or _positive_int(info, "last_heartbeat") is None:
            return None
        if not heartbeat_is_fresh(info, now_ms):
            return None
        return _parse_engine_identity(info)
    except (OSError, ValueError, OverflowError, subprocess.SubprocessError):
        return None


def prove_engine_identity(record: TrustedEngineRecord, *, timeout: float) -> bool:
    """Authenticate a fresh health challenge without disclosing either credential."""
    challenge = secrets.token_hex(32)
    expected = hmac.new(
        record.bearer_token.encode("ascii"),
        record.proof_message(challenge),
        hashlib.sha256,
    ).hexdigest()
    try:
        response = httpx.get(
            f"{record.base_url}/health",
            headers={CHALLENGE_HEADER: challenge},
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        )
        proof = response.headers.get(PROOF_HEADER, "")
        return (
            response.status_code == 200
            and proof.isascii()
            and hmac.compare_digest(proof, expected)
        )
    except httpx.HTTPError:
        return False
