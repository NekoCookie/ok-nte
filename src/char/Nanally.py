import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionIntent,
    CombatContext,
    Planner,
    RoleProfile,
)


class Nanally(BaseChar):
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

            ult_was_available = self.ultimate_available()  # [lw] yield前记录, 供大招放出容错判定
            ultimate_result = yield ultimate
            # [lw] click_ultimate 的"进没进动画"检测会被大招时停/targeting/声音闪避干扰, 误报
            #      "no effect"(返回False); 但只要大招CD已进(之前可用、现在不可用)就是真放出了,
            #      仍要站满6s, 不被误判跳过——否则大招放完瞬间被切走(如零的元素反应), 站场白丢。
            if ultimate_result or (ult_was_available and not self.ultimate_available()):
                self.perform_in_ult(context, skill)

        return self.plan(
            skill,
            ultimate,
            entry=entry,
        )

    def perform_in_ult(self, context: CombatContext, skill: ActionIntent):
        # [lw] 娜娜莉大招强制站场约 6 秒,期间持续平A。上游用"大招不可用"早退,但大招一
        # 放完就进CD=立即不可用,会在 ~1s 就退场、白白浪费强制站场。改为留满 6s;战斗真
        # 结束时由 normal_attack 内的 check_combat 抛出跳出,不会空打。
        start = time.time()
        skill_used = False
        while time.time() - start < 6:  # [lw] Do not leave field merely because ultimate enters CD.
            if not skill_used and context.is_action_allowed(self, skill):
                skill_used = self.click_skill()
            self.normal_attack()
            self.sleep(0.2)
        return skill_used
    
    def on_combat_end(self, chars):
        self.switch_other_char()
