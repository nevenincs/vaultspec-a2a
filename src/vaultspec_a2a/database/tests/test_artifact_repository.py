"""Tests for artifact repository path validation."""

from __future__ import annotations

import pytest

from ..artifact_repository import _validate_artifact_path


class TestValidateArtifactPath:
    """REVIEW-081: artifact path must be relative with no traversal."""

    def test_simple_relative_path(self) -> None:
        assert _validate_artifact_path("outputs/report.md") == "outputs/report.md"

    def test_single_filename(self) -> None:
        assert _validate_artifact_path("report.md") == "report.md"

    def test_deeply_nested(self) -> None:
        result = _validate_artifact_path("a/b/c/d.txt")
        assert result == "a/b/c/d.txt"

    def test_rejects_absolute_unix(self) -> None:
        with pytest.raises(ValueError, match="must be relative"):
            _validate_artifact_path("/etc/passwd")

    def test_rejects_absolute_windows(self) -> None:
        with pytest.raises(ValueError, match="must be relative"):
            _validate_artifact_path("C:/Users/secret.txt")

    def test_rejects_dotdot_traversal(self) -> None:
        with pytest.raises(ValueError, match="must not contain"):
            _validate_artifact_path("../../../etc/passwd")

    def test_rejects_embedded_dotdot(self) -> None:
        with pytest.raises(ValueError, match="must not contain"):
            _validate_artifact_path("outputs/../../secret.txt")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_artifact_path("")

    def test_normalizes_backslashes(self) -> None:
        result = _validate_artifact_path("outputs\\report.md")
        assert result == "outputs/report.md"

    def test_rejects_backslash_traversal(self) -> None:
        with pytest.raises(ValueError, match="must not contain"):
            _validate_artifact_path("outputs\\..\\..\\secret.txt")
