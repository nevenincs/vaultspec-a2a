"""Brand-asset contracts for the dashboard-bundled runtime."""

from __future__ import annotations

import ast
import hashlib
import struct
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_README_LOGO = _PROJECT_ROOT / "assets" / "logo.png"
_SPEC = _PROJECT_ROOT / "packaging" / "pyinstaller" / "vaultspec-a2a.spec"
_ICON = _SPEC.with_name("vaultspec.ico")

_EXPECTED_ICON_SIZES = {16, 32, 48, 64, 128, 256}
_EXPECTED_SHA256 = {
    _README_LOGO: "4f74b14c65308c84c6a24289c1999a64fbe61fef954101ff4945d1c807708f57",
    _ICON: "7291c0067ac4da1d3e7a31b6a0183b23eafed5611a687ab6a8f490e647504705",
}


def _ico_frames(path: Path) -> list[tuple[int, int, int, int]]:
    """Return ``(width, height, planes, bit_count)`` for every ICO entry."""
    payload = path.read_bytes()
    reserved, image_type, count = struct.unpack_from("<HHH", payload)
    assert (reserved, image_type) == (0, 1)
    assert len(payload) >= 6 + count * 16

    frames: list[tuple[int, int, int, int]] = []
    for index in range(count):
        offset = 6 + index * 16
        width, height, _colors, reserved_byte, planes, bit_count = struct.unpack_from(
            "<BBBBHH", payload, offset
        )
        assert reserved_byte == 0
        frames.append((width or 256, height or 256, planes, bit_count))
    return frames


def test_readme_uses_the_repository_logo_with_contextual_alt_text() -> None:
    readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert _README_LOGO.is_file()
    assert '<img src="assets/logo.png" alt="Vaultspec A2A logo" width="256">' in readme


def test_brand_assets_are_the_approved_derivatives() -> None:
    for path, expected in _EXPECTED_SHA256.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_application_icon_has_exactly_the_governed_frames() -> None:
    frames = _ico_frames(_ICON)

    assert len(frames) == len(_EXPECTED_ICON_SIZES)
    assert {(width, height) for width, height, _planes, _bits in frames} == {
        (size, size) for size in _EXPECTED_ICON_SIZES
    }
    assert all(planes == 1 for _width, _height, planes, _bits in frames)
    assert all(bit_count == 32 for _width, _height, _planes, bit_count in frames)


def test_pyinstaller_wires_the_icon_from_the_spec_directory_on_windows() -> None:
    tree = ast.parse(_SPEC.read_text(encoding="utf-8"), filename=str(_SPEC))
    assignments = {
        target.id: statement.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }

    spec_dir = assignments["_SPEC_DIR"]
    assert isinstance(spec_dir, ast.Call)
    assert isinstance(spec_dir.func, ast.Attribute)
    assert spec_dir.func.attr == "resolve"
    assert ast.unparse(spec_dir.func.value) == "Path(SPECPATH)"

    icon_path = assignments["_WINDOWS_ICON"]
    assert isinstance(icon_path, ast.BinOp)
    assert ast.unparse(icon_path) == "_SPEC_DIR / 'vaultspec.ico'"

    exe_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EXE"
    )
    icon_keyword = next(
        keyword for keyword in exe_call.keywords if keyword.arg == "icon"
    )
    assert ast.unparse(icon_keyword.value) == "str(_WINDOWS_ICON) if is_win else None"
