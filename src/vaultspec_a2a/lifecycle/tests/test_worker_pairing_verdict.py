"""Pairing evidence must fail closed, and eviction must need more than a verdict.

A worker that reports nothing looks identical to one this gateway never started:
a Compose worker, an operator's, a test's, or another gateway's orphan. Treating
that silence as ownership is how dispatch reached a foreign worker, so silence
classifies as unidentified and licenses nothing.

Eviction is a hard kill of another process, so it is deliberately narrower than
adoption: one verdict, and only for an armed desktop gateway reclaiming its own
earlier generation.
"""

from __future__ import annotations

import pytest

from ..pairing import (
    WorkerPairingVerdict,
    classify_worker_pairing,
    eviction_is_authorized,
)

_OURS = "a" * 32
_THEIRS = "b" * 32


def _classify(lifetime: str | None, generation: str | None, current: int = 3):
    return classify_worker_pairing(
        reported_lifetime=lifetime,
        reported_generation=generation,
        gateway_lifetime=_OURS,
        current_generation=current,
    )


def test_the_current_generation_is_owned() -> None:
    """The ordinary live case: our lifetime, our newest generation."""
    assert _classify(_OURS, "3") is WorkerPairingVerdict.OWNED


def test_an_earlier_generation_of_ours_is_a_prior_generation() -> None:
    """Ours, but superseded - the only case eviction may act on."""
    assert _classify(_OURS, "1") is WorkerPairingVerdict.PRIOR_GENERATION


def test_another_gateways_worker_is_foreign() -> None:
    """A different incarnation owns it; it may be serving live runs."""
    assert _classify(_THEIRS, "3") is WorkerPairingVerdict.FOREIGN


@pytest.mark.parametrize("lifetime", [None, "", "   "])
def test_blank_lifetime_evidence_is_unidentified(lifetime: str | None) -> None:
    """Silence is what a worker we never started looks like."""
    assert _classify(lifetime, "3") is WorkerPairingVerdict.UNIDENTIFIED


@pytest.mark.parametrize("generation", [None, "", "  ", "abc", "1.5", "-1", "0"])
def test_unusable_generation_evidence_is_unidentified(generation: str | None) -> None:
    """Our lifetime is not enough; the generation must also be readable."""
    assert _classify(_OURS, generation) is WorkerPairingVerdict.UNIDENTIFIED


def test_a_generation_we_never_issued_is_unidentified_not_newer() -> None:
    """A worker cannot hold a generation its gateway never minted."""
    assert _classify(_OURS, "99") is WorkerPairingVerdict.UNIDENTIFIED


def test_only_a_prior_generation_authorizes_eviction_and_only_when_armed() -> None:
    """Eviction is narrower than adoption; every other combination refuses."""
    for verdict in WorkerPairingVerdict:
        expected = verdict is WorkerPairingVerdict.PRIOR_GENERATION

        assert eviction_is_authorized(verdict, desktop_profile_armed=True) is expected
        assert eviction_is_authorized(verdict, desktop_profile_armed=False) is False


def test_an_unarmed_gateway_never_evicts_even_its_own_prior_generation() -> None:
    """Compose and dev share ports by design; killing there is not ours to do."""
    assert (
        eviction_is_authorized(
            WorkerPairingVerdict.PRIOR_GENERATION, desktop_profile_armed=False
        )
        is False
    )
