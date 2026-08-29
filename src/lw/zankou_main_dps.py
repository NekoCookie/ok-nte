"""[lw] Zankou main-DPS template backed by the current RU implementation."""

from src.char.Zankou import Zankou
from src.combat.planner import ActionSlot, ActionTag
from src.lw.combat_test_policy import LWCombatTestPolicyMixin
from src.lw.requiem_zankou_axis import (
    REQUIEM_IMPL_ID,
    ZANKOU_MAIN_DPS_IMPL_ID,
    coordinated_axis_partner,
    coordinated_axis_settings,
    perform_zankou_combat_axis,
)


class ZankouMainDps(LWCombatTestPolicyMixin, Zankou):
    """Expose RU Zankou as a separately selectable main-DPS template."""

    en_name = "Zankou Main DPS"
    cn_name = "残虹主C"
    AWAKENED_SECOND_ULTIMATE_WAIT = 0.8
    AWAKENED_SECOND_ULTIMATE_POLL_INTERVAL = 0.1

    def _has_coordinated_axis_partner(self):
        return coordinated_axis_partner(
            self,
            None,
            self_impl_id=ZANKOU_MAIN_DPS_IMPL_ID,
            partner_impl_id=REQUIEM_IMPL_ID,
        ) is not None

    def intro_motion_freeze_duration(self) -> float:
        if self._has_coordinated_axis_partner():
            return coordinated_axis_settings(self).zankou_intro_wait_duration
        return super().intro_motion_freeze_duration()

    def wait_intro(self, time_out=-1, click=True):
        """Keep Zankou's coordinated-axis entry silent until its heavy attack."""

        if not self._has_coordinated_axis_partner():
            return super().wait_intro(time_out=time_out, click=click)
        if not self.has_intro:
            return
        duration = self.intro_motion_freeze_duration() if time_out < 0 else time_out
        self.logger.info(f"zankou coordinated axis wait intro {duration:.2f}s without attack")
        self.sleep(duration)
        self.logger.info("zankou coordinated axis wait intro end")

    def should_force_off_field(self):
        return bool(getattr(self, "_coaxis_switch_pending", False))

    def switch_out(self):
        self._coaxis_switch_pending = False
        super().switch_out()

    def prepare_for_sound_dodge(self):
        """Release a coordinated-axis heavy input before dodge handling continues."""

        if not getattr(self, "_coaxis_heavy_held", False):
            return
        self.task.mouse_up()
        self._coaxis_heavy_held = False

    def _wait_for_awakened_second_ultimate(self) -> bool:
        deadline = self.now() + self.AWAKENED_SECOND_ULTIMATE_WAIT
        while True:
            if self.ultimate_available():
                self.logger.info("zankou awakened second ultimate available")
                return True
            remaining = deadline - self.now()
            if remaining <= 0:
                self.logger.info("zankou awakened second ultimate unavailable; continuing axis")
                return False
            self.sleep(min(self.AWAKENED_SECOND_ULTIMATE_POLL_INTERVAL, remaining))

    def combat_plan(self, context):
        partner = coordinated_axis_partner(
            self,
            context,
            self_impl_id=ZANKOU_MAIN_DPS_IMPL_ID,
            partner_impl_id=REQUIEM_IMPL_ID,
        )
        if partner is None:
            if self.lw_skills_disabled_for_test():
                return self._combat_test_normal_attack_plan()
            return super().combat_plan(context)

        ultimate = self.click_ultimate_action(
            reason="zankou coordinated-axis ultimate",
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
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
            if not self.lw_skills_disabled_for_test():
                awakened_double_ultimate = bool(self.find_ult_purple())
                ultimate_result = yield ultimate
                if ultimate_result and awakened_double_ultimate:
                    self.logger.info("zankou awakened first ultimate complete")
                    if self._wait_for_awakened_second_ultimate():
                        yield ultimate.repeat_for_entry()
            yield coaxis

        return self.plan(ultimate, coaxis, entry=entry)

    def _combat_test_normal_attack_plan(self):
        normal_attack = self.planner_action(
            tags={ActionTag.LEGACY_COMBO, ActionTag.DAMAGE, ActionTag.FIELD_TIME},
            slot=ActionSlot.LEGACY_COMBO,
            execute=lambda _: self.continues_normal_attack(1.5),
            name=f"{self}_test_normal_attacks",
            reason="zankou combat test normal attacks",
            priority_ready=lambda _: False,
        )

        def entry():
            yield normal_attack

        return self.plan(normal_attack, entry=entry)
