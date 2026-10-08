"""Fetch a pinned release artefact, refusing any bytes its pin does not name.

Every provisioner under ``dev/`` that installs an executable from a release -
the actionlint the workflow check runs, the Docker CLI plugins the rootless
integration fixtures need - downloads it the same way, and the two properties
that make that safe are stated here once rather than per provisioner:

* **The origin is literal.** The caller passes a path under ``github.com``,
  never a URL, and the scheme and host are written below as text. A variable
  URL can carry ``file:`` or any other scheme ``urlopen`` happens to handle;
  this way the only reachable origin is the one this module spells out.
* **The digest is checked before anything is written.** The caller receives
  the bytes only once they hash to the pinned SHA-256, so nothing unverified
  ever reaches the disk to be executed by mistake.

Stdlib only, so a provisioner that runs before anything is installed can use it.
"""

from __future__ import annotations

import hashlib
import urllib.request
from typing import Final

__all__ = ["MAX_DOWNLOAD_BYTES", "UnverifiedDownloadError", "download_verified"]

#: The most one artefact may weigh. A read is capped at one byte past this so
#: a runaway response cannot exhaust memory; anything truncated by the cap
#: then fails the digest, which is the check that decides.
MAX_DOWNLOAD_BYTES: Final[int] = 128 * 1024 * 1024


class UnverifiedDownloadError(RuntimeError):
    """A downloaded artefact is not the one its pinned digest names."""


def download_verified(path: str, sha256: str, *, timeout: float) -> bytes:
    """Fetch one artefact from ``github.com`` and return it once it verifies.

    Args:
        path: The artefact's path under ``https://github.com/``.
        sha256: The pinned hex SHA-256 the bytes must hash to.
        timeout: Seconds to wait on the connection before giving up.

    Returns:
        The artefact's bytes.

    Raises:
        UnverifiedDownloadError: When the bytes do not hash to ``sha256``.
        OSError: When the download itself failed; :mod:`urllib` reports
            network and HTTP failures as subclasses of it.
    """
    with urllib.request.urlopen(
        f"https://github.com/{path}", timeout=timeout
    ) as response:
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sha256:
        msg = (
            f"{path} does not match its pinned SHA-256\n"
            f"  expected {sha256}\n"
            f"  got      {digest}\n"
            "Refusing to use an unverified download."
        )
        raise UnverifiedDownloadError(msg)
    return payload
