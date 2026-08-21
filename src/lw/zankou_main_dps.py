"""[lw] Zankou main-DPS template backed by the current RU implementation."""

from src.char.Zankou import Zankou
from src.combat.planner import ActionSlot, ActionTag
from src.lw.requiem_zankou_axis import (
    REQUIEM_IMPL_ID,
    ZANKOU_MAIN_DPS_IMPL_ID,
    coordinated_axis_partner,
    perform_zankou_combat_axis,
)


class ZankouMainDps(Zankou):
    """Expose RU Zankou as a separately selectable main-DPS template."""

    en_name = "Zankou Main DPS"
    cn_name = "残虹主C"

    def combat_plan(self, context):
        partner = coordinated_axis_partner(
            self,
            context,
            self_impl_id=ZANKOU_MAIN_DPS_IMPL_ID,
            partner_impl_id=REQUIEM_IMPL_ID,
        )
        if partner is None:
            return super().combat_plan(context)

        ultimate = self.click_ultimate_action(reason="zankou coordinated-axis ultimate")
        coaxis = self.planner_action(
            tags={ActionTag.LEGACY_COMBO, ActionTag.DAMAGE, ActionTag.FIELD_TIME},
            slot=ActionSlot.LEGACY_COMBO,
            execute=lambda axis_context: perform_zankou_combat_axis(
                self,
                axis_context,
                partner,
            ),
            name=f"{self}_coordinated_axis",
            reason="zankou coordinated axis field time",
            priority_ready=lambda _: False,
        )

        def entry():
            yield ultimate
            yield coaxis

        return self.plan(ultimate, coaxis, entry=entry)
