import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionIntent,
    CombatContext,
    Planner,
    RoleProfile,
)
from src.lw.nanally_ext import NanallyExtMixin  # [lw]


class Nanally(NanallyExtMixin, BaseChar):  # [lw]
    cn_name = "娜娜莉"
    element = BaseChar.Element.GREEN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.MAIN_DPS,
            field_preference=Planner.FieldPreference.MAIN_DPS,
            max_field_time=1.5,
        )

    def combat_plan(self, context):
        skill = self.click_skill_action()
        ultimate = self.click_ultimate_action()

        def entry():
            skill_result = yield skill
            if skill_result and self.ultimate_available():
                self.sleep(0.6)

            ult_was_available = self.ultimate_available()  # [lw]
            ultimate_result = yield ultimate
            if self.lw_ultimate_action_landed(ultimate_result, ult_was_available):  # [lw]
                self.perform_in_ult(context, skill)

        return self.plan(
            skill,
            ultimate,
            entry=entry,
        )

    def perform_in_ult(self, context: CombatContext, skill: ActionIntent):
        start = time.time()
        skill_used = False
        while (elapsed := time.time() - start) < 6:
            if not self.lw_should_continue_ultimate_field(elapsed):  # [lw]
                break
            if not skill_used and context.is_action_allowed(self, skill):
                skill_used = self.click_skill()
            self.normal_attack()
            self.sleep(0.2)
        return skill_used
    
    def on_combat_end(self, chars):
        self.switch_other_char()
