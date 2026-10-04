"""Exercise the digest receipt's trust boundary without registry access."""

from __future__ import annotations

import pytest

from dev.container_publish import release_identity, validate_receipt


def receipt() -> dict[str, object]:
    return {
        "schema": 1,
        "tag": "v1.2.3",
        "repository": "nevenincs/vaultspec-a2a",
        "revision": "a" * 40,
        "platform": "linux/amd64",
        "images": {
            role: f"ghcr.io/nevenincs/vaultspec-a2a-{role}@sha256:{'b' * 64}"
            for role in ("gateway", "worker")
        },
    }


def test_receipt_accepts_complete_immutable_pair() -> None:
    assert set(validate_receipt(receipt(), "v1.2.3", "nevenincs/vaultspec-a2a")) == {
        "gateway",
        "worker",
    }


@pytest.mark.parametrize("tag", ["--help", "main", "v1.2.3; echo bad", "v1.2.3-rc1"])
def test_release_identity_refuses_nonrelease_input(tag: str) -> None:
    with pytest.raises(ValueError):
        release_identity(tag, "nevenincs/vaultspec-a2a")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", 2),
        ("platform", "linux/arm64"),
        ("revision", "main"),
        ("tag", "v9.9.9"),
        ("repository", "other/project"),
        ("images", {}),
        ("images", {"gateway": "ghcr.io/other/image:latest", "worker": "mutable"}),
    ],
)
def test_receipt_refuses_substitution(field: str, value: object) -> None:
    document = receipt()
    document[field] = value
    with pytest.raises(ValueError):
        validate_receipt(document, "v1.2.3", "nevenincs/vaultspec-a2a")
