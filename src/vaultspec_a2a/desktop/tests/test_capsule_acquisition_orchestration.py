"""Acquisition orchestration wiring, proven offline against real byte streams.

The orchestrators loop the proven ``acquire_artifact`` over a resolved
selection.  Wiring is proven offline by injecting real in-memory byte streams
through the official ``open_stream`` seam - each artifact is served the exact
bytes matching its pin - so the cache is populated without network.  A real
full-closure acquisition run is service-marked in the preparation path.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from io import BytesIO
from typing import TYPE_CHECKING

from vaultspec_a2a.desktop.capsule_input_authoring import (
    PinnedSource as _PinnedSource,
)
from vaultspec_a2a.desktop.capsule_input_authoring import (
    acquire_acp_closure,
    acquire_pinned_sources,
    acquire_python_closure,
)
from vaultspec_a2a.desktop.closure_inventory import _validate_sha512_sri
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    AcpClosureSelection,
    AcpNodeSelection,
    LockedWheel,
    PythonClosureSelection,
    PythonPackageSelection,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from vaultspec_a2a.desktop.capsule_input_authoring import ArtifactStreamOpener

_TAG = "cp313-cp313-win_amd64"


def _sri(payload: bytes) -> str:
    import base64

    return _validate_sha512_sri(
        "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    )


def _content_opener(bytes_by_url: dict[str, bytes]) -> ArtifactStreamOpener:
    @contextmanager
    def opener(url: str) -> Iterator[BytesIO]:
        yield BytesIO(bytes_by_url[url])

    return opener


def _wheel(name: str, payload: bytes) -> LockedWheel:
    filename = f"{name}-1.0.0-{_TAG}.whl"
    return LockedWheel(
        url=f"https://files.example.test/{filename}",
        filename=filename,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


def test_acquire_python_closure_populates_the_cache_by_content_address(
    tmp_path: Path,
) -> None:
    payloads = {"alpha": b"alpha wheel bytes", "beta": b"beta wheel bytes different"}
    wheels = {name: _wheel(name, body) for name, body in payloads.items()}
    packages = tuple(
        PythonPackageSelection(
            name=name,
            version="1.0.0",
            dependencies=(),
            wheels=(wheels[name],),
            compatible_wheels=(wheels[name],),
        )
        for name in payloads
    )
    selection = PythonClosureSelection(
        target=TargetTriple.WINDOWS_X86_64, roots=("alpha", "beta"), packages=packages
    )
    served = {wheels[name].url: body for name, body in payloads.items()}

    acquired = acquire_python_closure(
        selection, cache_root=tmp_path, open_stream=_content_opener(served)
    )

    assert set(acquired) == {"alpha", "beta"}
    for name, body in payloads.items():
        entry = acquired[name]
        assert entry.acquired.sha256 == hashlib.sha256(body).hexdigest()
        assert entry.acquired.path.read_bytes() == body
        assert entry.acquired.path.name == entry.wheel.sha256


def test_acquire_acp_closure_verifies_each_sha512_and_keys_by_install_path(
    tmp_path: Path,
) -> None:
    payloads = {
        "node_modules/@scope/a": b"tarball a",
        "node_modules/@scope/b": b"tarball b longer",
    }
    nodes = tuple(
        AcpNodeSelection(
            name=path.rsplit("node_modules/", 1)[-1],
            install_path=path,
            version="1.0.0",
            url=f"https://registry.example.test{path}.tgz",
            integrity=_sri(body),
            dependency_paths=(),
        )
        for path, body in payloads.items()
    )
    selection = AcpClosureSelection(
        target=TargetTriple.WINDOWS_X86_64,
        root_path="node_modules/@scope/a",
        packages=nodes,
    )
    served = {node.url: payloads[node.install_path] for node in nodes}

    acquired = acquire_acp_closure(
        selection, cache_root=tmp_path, open_stream=_content_opener(served)
    )

    assert set(acquired) == set(payloads)
    for path, body in payloads.items():
        assert acquired[path].sha256 == hashlib.sha256(body).hexdigest()
        assert acquired[path].path.read_bytes() == body


def test_acquire_pinned_sources_verifies_each_against_its_sha256(
    tmp_path: Path,
) -> None:
    bodies = (b"cpython source", b"node source", b"acp adapter", b"launcher stub")
    sources = tuple(
        _PinnedSource(
            url=f"https://downloads.example.test/source-{index}.tar.gz",
            sha256=hashlib.sha256(body).hexdigest(),
        )
        for index, body in enumerate(bodies)
    )
    served = {source.url: body for source, body in zip(sources, bodies, strict=True)}

    acquired = acquire_pinned_sources(
        sources, cache_root=tmp_path, open_stream=_content_opener(served)
    )

    assert len(acquired) == 4
    for item, body in zip(acquired, bodies, strict=True):
        assert item.sha256 == hashlib.sha256(body).hexdigest()
        assert item.path.read_bytes() == body
