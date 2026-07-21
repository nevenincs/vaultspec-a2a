"""Acquisition into the sha256-keyed content-addressed cache.

The verify, cache, idempotency, and fail-closed logic is proven offline against
real bytes streamed through the module's official ``open_stream`` seam - a real
binary stream, no mock or monkeypatch.  One ``service``-marked test drives the
default network path against a pinned upstream release over real HTTPS; the
default suite runs with ``-m 'not service'``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.capsule_input_authoring import (
    CapsuleInputAuthoringError,
    acquire_artifact,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from vaultspec_a2a.desktop.capsule_input_authoring import ArtifactStreamOpener

_REPO_ROOT = Path(__file__).resolve().parents[4]
_URL = "https://files.example.test/pkg-1.0-py3-none-any.whl"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sri(payload: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode(
        "ascii"
    )


def _stream_of(payload: bytes) -> ArtifactStreamOpener:
    """Build one real readable binary stream over exactly these bytes."""

    @contextmanager
    def opener(_url: str) -> Iterator[io.BytesIO]:
        source = io.BytesIO(payload)
        try:
            yield source
        finally:
            source.close()

    return opener


def test_acquire_writes_bytes_under_their_content_address(tmp_path: Path) -> None:
    payload = b"real wheel bytes for the closure"

    result = acquire_artifact(
        _URL,
        cache_root=tmp_path / "cache",
        expected_sha256=_sha256(payload),
        expected_size=len(payload),
        open_stream=_stream_of(payload),
    )

    assert result.sha256 == _sha256(payload)
    assert result.size == len(payload)
    assert result.path == (tmp_path / "cache").resolve() / _sha256(payload)
    assert result.path.read_bytes() == payload


def test_acquire_verifies_a_sha512_integrity_pin(tmp_path: Path) -> None:
    payload = b"real npm tarball bytes"

    result = acquire_artifact(
        "https://registry.example.test/tarball.tgz",
        cache_root=tmp_path / "cache",
        expected_sha512_sri=_sri(payload),
        open_stream=_stream_of(payload),
    )

    assert result.path.read_bytes() == payload
    # The cache key is the computed sha256 even when only a sha512 pin was given.
    assert result.path.name == _sha256(payload)
    assert result.size == len(payload)


def test_acquire_fails_closed_on_a_sha256_mismatch(tmp_path: Path) -> None:
    payload = b"bytes that will not match the pin"
    cache = tmp_path / "cache"

    with pytest.raises(CapsuleInputAuthoringError, match="sha256 does not match"):
        acquire_artifact(
            _URL,
            cache_root=cache,
            expected_sha256="0" * 64,
            open_stream=_stream_of(payload),
        )

    # Nothing is admitted under any content address when a pin fails.
    assert list(cache.resolve().iterdir()) == []


def test_acquire_fails_closed_on_a_sha512_mismatch(tmp_path: Path) -> None:
    payload = b"npm bytes with a bad integrity pin"

    with pytest.raises(CapsuleInputAuthoringError, match="sha512 does not match"):
        acquire_artifact(
            "https://registry.example.test/tarball.tgz",
            cache_root=tmp_path / "cache",
            expected_sha512_sri=_sri(b"different bytes entirely"),
            open_stream=_stream_of(payload),
        )


def test_acquire_fails_closed_on_a_size_mismatch(tmp_path: Path) -> None:
    payload = b"bytes longer than the declared size"

    with pytest.raises(CapsuleInputAuthoringError, match="exceeds its size bound"):
        acquire_artifact(
            _URL,
            cache_root=tmp_path / "cache",
            expected_sha256=_sha256(payload),
            expected_size=4,
            open_stream=_stream_of(payload),
        )


def test_acquire_is_idempotent_and_reuses_verified_cache(tmp_path: Path) -> None:
    payload = b"idempotent content-addressed bytes"
    cache = tmp_path / "cache"
    calls = 0

    @contextmanager
    def _counting_opener(_url: str) -> Iterator[io.BytesIO]:
        nonlocal calls
        calls += 1
        yield io.BytesIO(payload)

    first = acquire_artifact(
        _URL,
        cache_root=cache,
        expected_sha256=_sha256(payload),
        open_stream=_counting_opener,
    )
    second = acquire_artifact(
        _URL,
        cache_root=cache,
        expected_sha256=_sha256(payload),
        open_stream=_counting_opener,
    )

    assert first.path == second.path
    assert first.sha256 == second.sha256
    # The second call reuses the verified cache rather than re-fetching.
    assert calls == 1


def test_acquire_reacquires_when_cached_bytes_are_corrupted(tmp_path: Path) -> None:
    payload = b"authentic bytes for this content address"
    cache = tmp_path / "cache"
    cache.mkdir()
    digest = _sha256(payload)
    # A cache entry whose bytes no longer match its name must not be trusted.
    (cache / digest).write_bytes(b"tampered")

    result = acquire_artifact(
        _URL, cache_root=cache, expected_sha256=digest, open_stream=_stream_of(payload)
    )

    assert result.path.read_bytes() == payload


def test_acquire_requires_at_least_one_integrity_pin(tmp_path: Path) -> None:
    with pytest.raises(CapsuleInputAuthoringError, match="at least one integrity pin"):
        acquire_artifact(_URL, cache_root=tmp_path / "cache")


def test_acquire_rejects_a_non_https_url(tmp_path: Path) -> None:
    with pytest.raises(CapsuleInputAuthoringError, match="credential-free HTTPS"):
        acquire_artifact(
            "http://files.example.test/pkg.whl",
            cache_root=tmp_path / "cache",
            expected_sha256="0" * 64,
        )


def test_acquire_rejects_a_malformed_sha256_pin(tmp_path: Path) -> None:
    with pytest.raises(CapsuleInputAuthoringError, match="sha256 pin is malformed"):
        acquire_artifact(
            _URL,
            cache_root=tmp_path / "cache",
            expected_sha256="not-a-digest",
            open_stream=_stream_of(b"bytes"),
        )


@pytest.mark.service
def test_acquire_the_real_pinned_launcher_stub_over_the_network(tmp_path: Path) -> None:
    declaration = tomllib.loads(
        (_REPO_ROOT / "scripts" / "desktop_capsule_inputs.toml").read_bytes().decode()
    )["launcher_stub"]

    result = acquire_artifact(
        declaration["url"],
        cache_root=_REPO_ROOT / "dist" / "capsules" / ".cache" / "acquisition",
        expected_sha256=declaration["sha256"],
    )

    assert result.sha256 == declaration["sha256"]
    assert result.path.name == declaration["sha256"]
    assert hashlib.sha256(result.path.read_bytes()).hexdigest() == declaration["sha256"]
