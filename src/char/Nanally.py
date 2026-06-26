import time

from src.char.BaseChar import BaseChar


class Nanally(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def do_perform(self):
        self.wait_intro()
        skill = self.click_skill()[0]
        if self.ultimate_available() and skill:
            self.sleep(0.6)
        if self.click_ultimate():
            self.perform_in_ult()

    def perform_in_ult(self):
        # 娜娜莉大招强制站场约 6 秒,期间持续平A。原逻辑用"大招不可用"早退,但大招一
        # 放完就进CD=立即不可用,会在 ~1s 就退场、白白浪费强制站场。改为留满 6s;战斗真
        # 结束时由 normal_attack 内的 check_combat 抛出跳出,不会空打。
        start = time.time()
        while time.time() - start < 6:
            self.normal_attack()
            self.sleep(0.2)

    def do_fast_perform(self):
        self.wait_intro()
        self.click_skill()
