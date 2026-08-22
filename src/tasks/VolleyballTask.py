import re
import time

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
    MODE_AUTO = "自动闯关"
    MODE_SUP = "辅助扣发球"
    MODES = [MODE_EXP, MODE_AUTO]
    INFO_MATCH_COUNT = "已打比赛"
    INFO_WIN_COUNT = "赢球次数"
    INFO_LOSS_COUNT = "输球次数"
    INFO_LEVEL_STATUS = "关卡状态"
    LOSE_TEXT_RE = re.compile(r"L[O0](?:[S5][E3]?)?", re.IGNORECASE)
    LOSE_TEXT_ROI = (0.65, 0.07, 0.99, 0.27)
    SERVICE_ACTION_ROIS = (
        (0.978, 0.405, 0.986, 0.421),
        (0.978, 0.437, 0.986, 0.453),
    )
    SERVICE_ACTION_WHITE_THRESHOLD = 0.04
    SERVICE_RELEASE_CONFIRM_SECONDS = 0.5
    SERVICE_PHASE_WARNING_SECONDS = 10.0
    SERVICE_PHASE_HARD_TIMEOUT_SECONDS = 30.0
    POSITION_ADJUST_AFTER_HITS = 4

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
        self.win_count = 0
        self.loss_count = 0
        self._match_result_recorded = False
        self._play_count = 0
        self.reset_service_phase()

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
        self.win_count = 0
        self.loss_count = 0
        self._match_result_recorded = False
        self._play_count = 0
        self.reset_service_phase()
        self.info_set(self.INFO_MATCH_COUNT, self.match_count)
        self.info_set(self.INFO_WIN_COUNT, self.win_count)
        self.info_set(self.INFO_LOSS_COUNT, self.loss_count)
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
            if not self.find_exit():
                in_game = self.handle_missing_exit(in_game, skip_task)
                if not in_game:
                    self.sleep(0.1)
                    continue
                if self.handle_service():
                    self.sleep(0.1)
                    continue
                self.sleep(0.1)
                continue
            elif not in_game:
                if not self.begin_match():
                    self.sleep(0.1)
                    continue
                in_game = True

            if self.handle_service():
                self.sleep(0.1)
                continue

            if self.is_spike():
                self.log_info("in spike")
                self.wait_until(lambda: not self.is_spike(), time_out=1)
                self.sleep(0.7)
                self.send_key("k")

            key, switch_key = self.play_once(key, switch_key)
            self.sleep(0.1)

    def begin_match(self):
        if not self.wait_until(
            self.find_exit,
            settle_time=1,
            time_out=1.5,
            raise_if_not_found=False,
        ):
            return False
        self._match_result_recorded = False
        self._play_count = 0
        self.reset_service_phase()
        self.log_info("game begin")
        if not self.handle_service():
            self.log_info("not service")
        return True

    def handle_service(self):
        now = time.monotonic()
        if not self.is_service():
            return self.handle_service_release(now)

        self._service_release_started_at = None
        if self._service_phase_active:
            self.check_service_phase_timeout(now)
            return True

        self._service_phase_active = True
        self._service_phase_started_at = now
        self._service_phase_warning_logged = False
        self.log_info("new service phase")
        self.send_key("j")
        self.sleep(2.5)
        self.send_key("k")
        return True

    def handle_service_release(self, now):
        if not self._service_phase_active:
            return False

        if self._service_release_started_at is None:
            self._service_release_started_at = now
            return True

        self.check_service_phase_timeout(now)
        if now - self._service_release_started_at < self.SERVICE_RELEASE_CONFIRM_SECONDS:
            return True

        self.log_info("service phase cleared")
        self.reset_service_phase()
        return False

    def check_service_phase_timeout(self, now):
        elapsed = now - self._service_phase_started_at
        if elapsed >= self.SERVICE_PHASE_HARD_TIMEOUT_SECONDS:
            raise TaskDisabledException("Serve UI did not clear before the safety timeout")
        if elapsed >= self.SERVICE_PHASE_WARNING_SECONDS and not self._service_phase_warning_logged:
            self._service_phase_warning_logged = True
            self.log_warning("serve UI has not cleared; input remains locked")

    def reset_service_phase(self):
        self._service_phase_active = False
        self._service_phase_started_at = 0.0
        self._service_release_started_at = None
        self._service_phase_warning_logged = False

    def handle_missing_exit(self, in_game, skip_task):
        if self.handle_match_end():
            return False
        if not in_game:
            skip_task.check_skip()
        return in_game

    def play_once(self, key, switch_key):
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP | self.MODE_AUTO:
                if self._play_count >= self.POSITION_ADJUST_AFTER_HITS:
                    self.sleep(0.5)
                    self.send_key("a", down_time=0.1)
                    self.sleep(0.1)
                    self.send_key("s", down_time=0.1)
                    self._play_count = 0
                    return key, switch_key
                if self.send_key(key, interval=0.5):
                    self._play_count += 1
                    return ("j" if switch_key else "k"), not switch_key
            case self.MODE_SUP:
                pass
        return key, switch_key

    def handle_match_end(self):
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP:
                if box := self.find_one(Labels.volleyball_restart):
                    self.handle_match_result(box, won=not self.is_match_lost(), next_level=False)
                    return True
            case self.MODE_AUTO:
                if box := self.find_one(Labels.volleyball_restart):
                    self.sleep(1)
                    won = not self.is_match_lost()
                    next_level = won and self.has_three_stars()
                    if next_level:
                        box = self.find_one(Labels.volleyball_next) or box
                    self.handle_match_result(box, won=won, next_level=next_level)
                    return True
            case self.MODE_SUP:
                pass
        return False

    def handle_match_result(self, box, won, next_level):
        self.reset_service_phase()
        if won:
            status = "进入下一关" if next_level else "已到达最终关"
        else:
            status = "本局失败"
        self.info_set(self.INFO_LEVEL_STATUS, status)
        self.click_match_end_button(box, won)

    def click_match_end_button(self, box, won):
        self.operate_click(box, after_sleep=0.5)
        if self._match_result_recorded:
            return
        self._match_result_recorded = True
        self.match_count += 1
        self.info_set(self.INFO_MATCH_COUNT, self.match_count)
        if won:
            self.win_count += 1
            self.info_set(self.INFO_WIN_COUNT, self.win_count)
        else:
            self.loss_count += 1
            self.info_set(self.INFO_LOSS_COUNT, self.loss_count)

    def has_three_stars(self):
        stars_box = self.get_box_by_name(Labels.box_volleyball_stars)
        return len(self.find_feature(Labels.volleyball_star, box=stars_box)) == 3

    def is_match_lost(self):
        box = self.box_of_screen(*self.LOSE_TEXT_ROI, name="volleyball_lose_text")
        return bool(self.ocr(box=box, match=self.LOSE_TEXT_RE))

    def is_service(self):
        from src import text_white_color

        return all(
            self.calculate_color_percentage(
                text_white_color,
                self.box_of_screen(*roi),
            )
            > self.SERVICE_ACTION_WHITE_THRESHOLD
            for roi in self.SERVICE_ACTION_ROIS
        )

    def is_spike(self):
        box = self.box_of_screen(0.8562, 0.8500, 0.9137, 0.9243, hcenter=True)
        return self.calculate_color_percentage(spike_bule_color, box) > 0.06


spike_bule_color = {
    "r": (71, 100),
    "g": (155, 175),
    "b": (167, 187),
}
