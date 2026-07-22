from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vaultspec_a2a.desktop.capsule_input_authoring import (
    CapsuleInputAuthoringError,
    select_target_wheel,
    target_platform_tags,
    target_supported_tags,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    LockedWheel,
    PythonPackageSelection,
    resolve_python_closure_selection,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYTHON_RUNTIME = "3.13.5"

# Fixed vectors over the derived platform sequence.  A packaging upgrade that
# reorders or renames tags must fail here rather than silently change which
# wheel each capsule ships.
_EXPECTED_PLATFORM_TAGS = {
    TargetTriple.WINDOWS_X86_64: ("win_amd64",),
    TargetTriple.LINUX_X86_64: (
        "manylinux_2_28_x86_64",
        "manylinux_2_27_x86_64",
        "manylinux_2_26_x86_64",
        "manylinux_2_25_x86_64",
        "manylinux_2_24_x86_64",
        "manylinux_2_23_x86_64",
        "manylinux_2_22_x86_64",
        "manylinux_2_21_x86_64",
        "manylinux_2_20_x86_64",
        "manylinux_2_19_x86_64",
        "manylinux_2_18_x86_64",
        "manylinux_2_17_x86_64",
        "manylinux2014_x86_64",
        "manylinux_2_16_x86_64",
        "manylinux_2_15_x86_64",
        "manylinux_2_14_x86_64",
        "manylinux_2_13_x86_64",
        "manylinux_2_12_x86_64",
        "manylinux2010_x86_64",
        "manylinux_2_11_x86_64",
        "manylinux_2_10_x86_64",
        "manylinux_2_9_x86_64",
        "manylinux_2_8_x86_64",
        "manylinux_2_7_x86_64",
        "manylinux_2_6_x86_64",
        "manylinux_2_5_x86_64",
        "manylinux1_x86_64",
    ),
    TargetTriple.LINUX_ARM64: (
        "manylinux_2_28_aarch64",
        "manylinux_2_27_aarch64",
        "manylinux_2_26_aarch64",
        "manylinux_2_25_aarch64",
        "manylinux_2_24_aarch64",
        "manylinux_2_23_aarch64",
        "manylinux_2_22_aarch64",
        "manylinux_2_21_aarch64",
        "manylinux_2_20_aarch64",
        "manylinux_2_19_aarch64",
        "manylinux_2_18_aarch64",
        "manylinux_2_17_aarch64",
        "manylinux2014_aarch64",
    ),
    TargetTriple.MACOS_ARM64: (
        "macosx_13_0_arm64",
        "macosx_13_0_universal2",
        "macosx_12_0_arm64",
        "macosx_12_0_universal2",
        "macosx_11_0_arm64",
        "macosx_11_0_universal2",
        "macosx_10_16_universal2",
        "macosx_10_15_universal2",
        "macosx_10_14_universal2",
        "macosx_10_13_universal2",
        "macosx_10_12_universal2",
        "macosx_10_11_universal2",
        "macosx_10_10_universal2",
        "macosx_10_9_universal2",
        "macosx_10_8_universal2",
        "macosx_10_7_universal2",
        "macosx_10_6_universal2",
        "macosx_10_5_universal2",
        "macosx_10_4_universal2",
    ),
}
# The first supported tag each target derives, most specific compiled wheel.
_EXPECTED_LEADING_TAG = {
    TargetTriple.WINDOWS_X86_64: "cp313-cp313-win_amd64",
    TargetTriple.LINUX_X86_64: "cp313-cp313-manylinux_2_28_x86_64",
    TargetTriple.LINUX_ARM64: "cp313-cp313-manylinux_2_28_aarch64",
    TargetTriple.MACOS_ARM64: "cp313-cp313-macosx_13_0_arm64",
}


def _committed_python_selection(
    target: TargetTriple,
) -> dict[str, PythonPackageSelection]:
    selection = resolve_python_closure_selection(
        lock_bytes=(_REPO_ROOT / "uv.lock").read_bytes(),
        target=target,
        root_package="vaultspec-a2a",
        python_full_version=_PYTHON_RUNTIME,
    )
    return selection.by_name()


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_platform_tag_order_matches_the_fixed_vector(target: TargetTriple) -> None:
    assert target_platform_tags(target) == _EXPECTED_PLATFORM_TAGS[target]


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_supported_tags_lead_with_the_most_specific_compiled_tag(
    target: TargetTriple,
) -> None:
    tags = target_supported_tags(target)

    assert str(tags[0]) == _EXPECTED_LEADING_TAG[target]
    # Pure-Python wheels are admitted but must rank last, never ahead of a
    # compiled wheel for the same package.
    assert str(tags[-1]) == "py30-none-any"
    assert len(tags) == len(set(tags))


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_supported_tags_never_admit_a_foreign_platform(
    target: TargetTriple,
) -> None:
    foreign = {
        TargetTriple.WINDOWS_X86_64: ("macosx", "manylinux", "musllinux"),
        TargetTriple.LINUX_X86_64: ("macosx", "win_amd64", "musllinux", "aarch64"),
        TargetTriple.LINUX_ARM64: ("macosx", "win_amd64", "musllinux", "x86_64"),
        TargetTriple.MACOS_ARM64: ("manylinux", "win_amd64", "musllinux"),
    }[target]

    for tag in target_supported_tags(target):
        if tag.platform == "any":
            continue
        assert not any(token in tag.platform for token in foreign)


def test_platform_tags_reject_a_non_target() -> None:
    non_target: Any = object()
    with pytest.raises(CapsuleInputAuthoringError, match="target is invalid"):
        target_platform_tags(non_target)


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_selects_a_compiled_wheel_over_the_pure_python_fallback(
    target: TargetTriple,
) -> None:
    # sqlalchemy ships both a target-native cp313 wheel and py3-none-any; the
    # capsule must carry the C extensions, not the pure-Python fallback.
    package = _committed_python_selection(target)["sqlalchemy"]

    chosen = select_target_wheel(package, target=target)

    assert chosen in package.compatible_wheels
    assert "py3-none-any" not in chosen.filename
    assert "cp313" in chosen.filename


@pytest.mark.parametrize(
    ("target", "package_name", "expected"),
    (
        (
            TargetTriple.LINUX_X86_64,
            "cryptography",
            "cryptography-49.0.0-cp311-abi3-manylinux_2_28_x86_64.whl",
        ),
        (
            TargetTriple.LINUX_ARM64,
            "cryptography",
            "cryptography-49.0.0-cp311-abi3-manylinux_2_28_aarch64.whl",
        ),
        (
            TargetTriple.MACOS_ARM64,
            "regex",
            "regex-2026.7.10-cp313-cp313-macosx_11_0_arm64.whl",
        ),
        (
            TargetTriple.MACOS_ARM64,
            "websockets",
            "websockets-16.1-cp313-cp313-macosx_11_0_arm64.whl",
        ),
    ),
)
def test_selection_prefers_the_highest_ranked_admitted_wheel(
    target: TargetTriple, package_name: str, expected: str
) -> None:
    package = _committed_python_selection(target)[package_name]

    chosen = select_target_wheel(package, target=target)

    assert chosen.filename == expected


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_every_resolved_package_selects_exactly_one_wheel(
    target: TargetTriple,
) -> None:
    for package in _committed_python_selection(target).values():
        chosen = select_target_wheel(package, target=target)
        assert chosen in package.compatible_wheels


def test_selection_is_deterministic() -> None:
    package = _committed_python_selection(TargetTriple.LINUX_X86_64)["websockets"]

    first = select_target_wheel(package, target=TargetTriple.LINUX_X86_64)
    second = select_target_wheel(package, target=TargetTriple.LINUX_X86_64)

    assert first == second


def test_selection_fails_closed_when_no_wheel_is_admitted() -> None:
    package = PythonPackageSelection(
        name="example",
        version="1.0.0",
        dependencies=(),
        wheels=(
            LockedWheel(
                url="https://files.pythonhosted.org/packages/example-1.0.0-cp313-cp313-macosx_11_0_arm64.whl",
                filename="example-1.0.0-cp313-cp313-macosx_11_0_arm64.whl",
                sha256="0" * 64,
                size=1,
            ),
        ),
        compatible_wheels=(),
    )

    with pytest.raises(
        CapsuleInputAuthoringError, match="no wheel in the lock supports"
    ):
        select_target_wheel(package, target=TargetTriple.LINUX_X86_64)


def test_selection_breaks_a_tag_tie_by_descending_build_then_filename() -> None:
    # Two wheels sharing the top supported tag: the higher build tag wins, and
    # with no build tag present the filename decides.
    base_url = "https://files.pythonhosted.org/packages/"
    filenames = (
        "sample-1.0.0-1-cp313-cp313-win_amd64.whl",
        "sample-1.0.0-2-cp313-cp313-win_amd64.whl",
        "sample-1.0.0-cp313-cp313-win_amd64.whl",
    )
    wheels = tuple(
        LockedWheel(
            url=f"{base_url}{name}",
            filename=name,
            sha256=f"{index}" * 64,
            size=index + 1,
        )
        for index, name in enumerate(filenames)
    )
    package = PythonPackageSelection(
        name="sample",
        version="1.0.0",
        dependencies=(),
        wheels=wheels,
        compatible_wheels=wheels,
    )

    chosen = select_target_wheel(package, target=TargetTriple.WINDOWS_X86_64)

    assert chosen.filename == "sample-1.0.0-2-cp313-cp313-win_amd64.whl"
