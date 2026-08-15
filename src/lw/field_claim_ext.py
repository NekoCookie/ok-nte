"""[lw] FieldClaim helpers for LW-only switch priorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.combat.planner.types import ExpectedEntry, FieldClaim, FieldClaimLevel

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar


@dataclass(slots=True)
class LwPreemptiveFieldClaim(FieldClaim):
    """A LW claim that must be considered before automatic element reactions."""


def lw_preemptive_field_claim(
    source: "BaseChar | str | None" = None,
    reason: str = "",
    expected_entry: ExpectedEntry | None = None,
    level: FieldClaimLevel = FieldClaimLevel.HIGH,
) -> FieldClaim:
    """Create the LW-only preemptive resource claim without changing RU FieldClaim."""

    if isinstance(source, str) and not reason:
        reason = source
        source = None
    source_id = source.index if source is not None else -1
    if source is not None and not reason:
        reason = FieldClaim.default_reason(source, level)
    return LwPreemptiveFieldClaim(
        _source=source_id,
        level=level,
        reason=reason,
        expected_entry=expected_entry,
    )


def is_lw_preemptive_field_claim(claim: FieldClaim) -> bool:
    """Return whether a standard FieldClaim carries the LW-only priority policy."""

    return isinstance(claim, LwPreemptiveFieldClaim)
