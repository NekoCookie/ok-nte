import re

from ok import TaskDisabledException

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.tasks.trigger.SkipDialogTask import SkipDialogTask

INST = "进入比赛后开始任务"
EN_INST = "Start the mission after entering the game"


class VolleyballTask(NTEOneTimeTask, BaseNTETask):
    CONF_MODE = "模式"
    MODE_EXP = "刷经验"
    MODE_SUP = "辅助扣发球"
    MODES = [MODE_EXP]
    INFO_MATCH_COUNT = "已打比赛"
    INFO_LEVEL_STATUS = "关卡状态"
    NEXT_LEVEL_TEXT_RE = re.compile(r"下一关|next(?:\s+level)?", re.IGNORECASE)
    NEXT_LEVEL_TEXT_ROI = (0.07, 0.72, 0.16, 0.79)
    NEXT_LEVEL_BUTTON_ROI = (0.025, 0.72, 0.072, 0.79)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "排球之星"
        self.default_config.update(
            {
                self.CONF_MODE: self.MODE_EXP,
            }
        )
        self.config_type.update(
            {
                self.CONF_MODE: {
                    "type": "drop_down",
                    "options": self.MODES,
                }
            }
        )
        self.instructions = INST if self.is_chinese() else EN_INST
        self.sleep_check_interval = 0.2
        self.match_count = 0

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("VolleyballTask error", e)
            raise

    def do_run(self):
        self.match_count = 0
        self.info_set(self.INFO_MATCH_COUNT, self.match_count)
        self.info_set(self.INFO_LEVEL_STATUS, "进行中")
        return self.auto_play()

    def sleep_check(self):
        super().sleep_check()
        if self.check_monthly_card():
            self.handle_monthly_card()

    def auto_play(self):
        skip_task = self.get_task_by_class(SkipDialogTask)
        switch_key = False
        key = "j"
        in_game = True
        while True:
            if self.find_exit():
                if not in_game:
                    if not self.begin_match():
                        continue
                    in_game = True

                if self.is_spike():
                    self.log_info("in spike")
                    self.wait_until(lambda: not self.is_spike(), time_out=1)
                    self.sleep(0.7)
                    self.send_key("k")

                key, switch_key = self.play_once(key, switch_key)
            else:
                in_game = self.handle_missing_exit(in_game, skip_task)
            self.sleep(0.1)

    def begin_match(self):
        if not self.wait_until(
            self.find_exit,
            settle_time=1,
            time_out=1.5,
            raise_if_not_found=False,
        ):
            return False
        self.log_info("game begin")
        if self.is_service():
            self.log_info("is service")
            self.send_key("j")
            self.sleep(2.5)
            self.send_key("k")
        else:
            self.log_info("not service")
        return True

    def handle_missing_exit(self, in_game, skip_task):
        if self.handle_match_end():
            return False
        skip_task.check_skip()
        return in_game

    def play_once(self, key, switch_key):
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP:
                if self.send_key(key, interval=0.5):
                    return ("j" if switch_key else "k"), not switch_key
            case self.MODE_SUP:
                pass
        return key, switch_key

    def handle_match_end(self):
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP:
                if box := self.find_next_level_button():
                    self.info_set(self.INFO_LEVEL_STATUS, "进入下一关")
                    self.click_match_end_button(box)
                    return True
                elif box := self.find_one(Labels.volleyball_restart):
                    self.info_set(self.INFO_LEVEL_STATUS, "已到达最终关")
                    self.click_match_end_button(box)
                    return True
            case self.MODE_SUP:
                pass
        return False

    def click_match_end_button(self, box):
        self.operate_click(box, after_sleep=0.5)
        self.match_count += 1
        self.info_set(self.INFO_MATCH_COUNT, self.match_count)

    def find_next_level_button(self):
        text_box = self.box_of_screen(*self.NEXT_LEVEL_TEXT_ROI, name="volleyball_next_text")
        if self.ocr(box=text_box, match=self.NEXT_LEVEL_TEXT_RE):
            return self.box_of_screen(*self.NEXT_LEVEL_BUTTON_ROI, name="volleyball_next")
        return None

    def is_service(self):
        from src import text_white_color

        upper = self.box_of_screen(0.947, 0.405, 0.965, 0.419)
        lower = self.box_of_screen(0.947, 0.514, 0.965, 0.530)
        upper_white = self.calculate_color_percentage(text_white_color, upper)
        lower_white = self.calculate_color_percentage(text_white_color, lower)
        return upper_white > lower_white

    def is_spike(self):
        box = self.box_of_screen(0.8562, 0.8500, 0.9137, 0.9243, hcenter=True)
        return self.calculate_color_percentage(spike_bule_color, box) > 0.06


spike_bule_color = {
    "r": (71, 100),
    "g": (155, 175),
    "b": (167, 187),
}
