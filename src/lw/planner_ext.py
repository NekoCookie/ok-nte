"""[lw] CombatPlanner policy extensions kept outside the RU planner contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.lw.field_claim_ext import is_lw_preemptive_field_claim

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar
    from src.combat.planner.context import CombatContext
    from src.combat.planner.types import SwitchDecision


class CombatPlannerExtMixin:
    """LW switch policy using the stable RU CombatPlan and FieldClaim contracts."""

    def lw_preemptive_field_claim_decision(
        self,
        current_char: "BaseChar",
        context: "CombatContext",
        has_intro: bool,
    ) -> "SwitchDecision | None":
        """Choose an LW resource claim that must run before automatic reactions."""

        from src.combat.planner.types import FIELD_CLAIM_SCORES, SwitchDecision

        candidates = []
        for char in self.state.chars:
            if char == current_char or not self._can_switch_to(char):
                continue
            claims = [
                claim
                for claim in self._claims_for(char, context)
                if claim.matches_char(char) and is_lw_preemptive_field_claim(claim)
            ]
            if not claims:
                continue
            claim = max(claims, key=lambda item: FIELD_CLAIM_SCORES.get(item.level, 0))
            candidates.append(
                (
                    FIELD_CLAIM_SCORES.get(claim.level, 0),
                    -getattr(char, "last_perform", 0),
                    -getattr(char, "index", 0),
                    char,
                    claim,
                )
            )

        if not candidates:
            return None
        _, _, _, target, claim = max(candidates, key=lambda item: item[:3])
        return SwitchDecision(
            target=target,
            reason=f"preemptive field claim: {claim.reason}",
            priority=999600,
            has_intro=has_intro,
            expected_entry=claim.expected_entry,
        )

    def lw_combat_start_preemptive_decision(
        self, current_char: "BaseChar | None"
    ) -> "SwitchDecision | None":
        """Allow confirmed LW support resources to prepare before regular combat starts."""

        if current_char is None:
            return None
        from src.combat.planner.types import Role

        if current_char.describe_role().role == Role.SUPPORT:
            return None
        return self.lw_preemptive_field_claim_decision(
            current_char,
            self.context_for(current_char, {}),
            has_intro=False,
        )
