import re
import time
from enum import StrEnum

from ok import TaskDisabledException

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.tasks.trigger.SkipDialogTask import SkipDialogTask

INST = "进入比赛后开始任务"
EN_INST = "Start the mission after entering the game"


# [lw] The local volleyball HUD is the reliable source for match phase transitions.
class VolleyballMatchState(StrEnum):
    WAITING = "waiting"
    SERVICE = "service"
    RALLY = "rally"
    SPIKE_CUE = "spike_cue"
    SPIKE_ACTION = "spike_action"
    UNKNOWN = "unknown"


class VolleyballTask(NTEOneTimeTask, BaseNTETask):
    CONF_MODE = "模式"
    CONF_SERVE_DELAY = "发球等待时间"
    CONF_PLAY_INTERVAL = "普通回合按键间隔"
    CONF_POSITION_ADJUST = "每4次按键调整位置"
    MODE_EXP = "刷经验"
    MODE_AUTO = "自动闯关"
    MODE_SUP = "辅助扣发球"
    MODES = [MODE_EXP, MODE_AUTO]
    INFO_MATCH_COUNT = "已打比赛"
    INFO_WIN_COUNT = "赢球次数"
    INFO_LOSS_COUNT = "输球次数"
    INFO_LEVEL_STATUS = "关卡状态"
    LOSE_TEXT_RE = re.compile(r"L[O0](?:[S5][E3]?)?", re.IGNORECASE)
    WIN_TEXT_RE = re.compile(r"W[I1L]N", re.IGNORECASE)
    NEXT_LEVEL_ACTION_RE = re.compile(r"下一关|NEXT(?:\s+LEVEL)?", re.IGNORECASE)
    RESTART_ACTION_RE = re.compile(r"重新开始|RESTART", re.IGNORECASE)
    RESULT_TEXT_ROI = (0.65, 0.07, 0.99, 0.27)
    RESULT_ACTIONS_ROI = (0.02, 0.70, 0.30, 0.98)
    STAR_ROIS = (
        (0.941, 0.521, 0.964, 0.563),
        (0.941, 0.575, 0.964, 0.617),
        (0.941, 0.629, 0.964, 0.671),
    )
    STAR_GOLD_COLOR = {
        "r": (230, 255),
        "g": (170, 255),
        "b": (0, 140),
    }
    STAR_GOLD_THRESHOLD = 0.15
    # [lw] Right-side key glyphs provide a fast state signal without OCR or model inference.
    SERVICE_ACTION_ROIS = (
        (0.978, 0.405, 0.986, 0.421),
        (0.978, 0.437, 0.986, 0.453),
    )
    RALLY_ACTION_ROIS = (
        (0.978, 0.518, 0.986, 0.534),
        (0.978, 0.550, 0.986, 0.566),
    )
    SPIKE_ACTION_ROIS = (
        (0.978, 0.655, 0.986, 0.671),
        (0.978, 0.687, 0.986, 0.703),
        (0.975, 0.717, 0.993, 0.743),
    )
    SERVICE_ACTION_WHITE_THRESHOLD = 0.04
    DEFAULT_SERVE_DELAY = 2.5
    MIN_SERVE_DELAY = 0.5
    MAX_SERVE_DELAY = 5.0
    SERVE_DELAY_RANGE_ERROR = "发球等待时间必须在0.5到5.0秒之间"
    DEFAULT_PLAY_INTERVAL = 0.5
    MIN_PLAY_INTERVAL = 0.1
    MAX_PLAY_INTERVAL = 2.0
    PLAY_INTERVAL_RANGE_ERROR = "普通回合按键间隔必须在0.1到2.0秒之间"
    DEFAULT_POSITION_ADJUST = True
    SERVICE_PHASE_WARNING_SECONDS = 10.0
    MATCH_RECOGNITION_INTERVAL = 0.05
    MATCH_SIGNAL_GRACE_SECONDS = 0.8
    MATCH_END_CHECK_INTERVAL_SECONDS = 0.5
    UNKNOWN_STATE_WARNING_SECONDS = 10.0
    POSITION_ADJUST_AFTER_HITS = 4
    MATCH_STATE_LABELS = {
        VolleyballMatchState.WAITING: "等待比赛",
        VolleyballMatchState.SERVICE: "发球",
        VolleyballMatchState.RALLY: "接球/进攻",
        VolleyballMatchState.SPIKE_CUE: "扣球",
        VolleyballMatchState.SPIKE_ACTION: "扣球",
        VolleyballMatchState.UNKNOWN: "等待识别",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "排球之星"
        self.default_config.update(
            {
                self.CONF_MODE: self.MODE_EXP,
                self.CONF_SERVE_DELAY: self.DEFAULT_SERVE_DELAY,
                self.CONF_PLAY_INTERVAL: self.DEFAULT_PLAY_INTERVAL,
                self.CONF_POSITION_ADJUST: self.DEFAULT_POSITION_ADJUST,
            }
        )
        self.config_description.update(
            {
                self.CONF_SERVE_DELAY: "抛球后等待多久再按发球键, 可设置0.5到5.0秒, 默认2.5秒. 运行中修改会在下一次发球时生效",
                self.CONF_PLAY_INTERVAL: "普通回合 J/K 的最短按键间隔, 可设置0.1到2.0秒, 默认0.5秒. 运行中修改会在下一次按键时生效",
                self.CONF_POSITION_ADJUST: "每成功按4次 J/K 后执行 A -> S 位置调整, 默认开启. 关闭后不会中断普通回合按键",
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
        self.reset_match_state()

    def validate_config(self, key, value):
        if key == self.CONF_SERVE_DELAY:
            try:
                delay = float(value)
            except (TypeError, ValueError):
                return self.SERVE_DELAY_RANGE_ERROR
            if not self.MIN_SERVE_DELAY <= delay <= self.MAX_SERVE_DELAY:
                return self.SERVE_DELAY_RANGE_ERROR
        if key == self.CONF_PLAY_INTERVAL:
            try:
                interval = float(value)
            except (TypeError, ValueError):
                return self.PLAY_INTERVAL_RANGE_ERROR
            if not self.MIN_PLAY_INTERVAL <= interval <= self.MAX_PLAY_INTERVAL:
                return self.PLAY_INTERVAL_RANGE_ERROR
        return super().validate_config(key, value)

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
        self.reset_match_state()
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
        # [lw] Keep recognizing the local volleyball HUD instead of stopping on one missed signal.
        skip_task = self.get_task_by_class(SkipDialogTask)
        switch_key = False
        key = "j"
        match_started = False
        while True:
            now = time.monotonic()
            match_state = self.get_match_state()
            if match_state is None:
                if self.should_handle_match_end(now) and self.handle_match_end():
                    match_started = False
                    self.reset_match_state()
                    self.sleep(self.MATCH_RECOGNITION_INTERVAL)
                    continue

                skip_task.check_skip()
                service_releasing = self.handle_service(is_service=False)
                unknown_duration = self.mark_match_state_unknown(now)
                if (
                    not service_releasing
                    and self._last_recognized_match_state == VolleyballMatchState.RALLY
                    and unknown_duration < self.MATCH_SIGNAL_GRACE_SECONDS
                ):
                    key, switch_key = self.play_once(key, switch_key)
                self.sleep(self.MATCH_RECOGNITION_INTERVAL)
                continue

            if not match_started:
                self.begin_match()
                match_started = True
            self.mark_match_state(match_state)
            if match_state not in {
                VolleyballMatchState.SPIKE_CUE,
                VolleyballMatchState.SPIKE_ACTION,
            }:
                self.reset_spike_phase()

            if match_state == VolleyballMatchState.SERVICE:
                self.handle_service(is_service=True)
            else:
                if self.handle_service(is_service=False):
                    self.sleep(self.MATCH_RECOGNITION_INTERVAL)
                    continue
                if match_state == VolleyballMatchState.SPIKE_CUE:
                    self.handle_spike_cue()
                elif match_state == VolleyballMatchState.SPIKE_ACTION:
                    self.handle_spike_action()
                else:
                    key, switch_key = self.play_once(key, switch_key)

            self.sleep(self.MATCH_RECOGNITION_INTERVAL)

    def begin_match(self):
        self._match_result_recorded = False
        self._play_count = 0
        self.reset_service_phase()
        self.reset_spike_phase()
        self.log_info("game begin")
        return True

    def get_match_state(self):
        if self.is_service():
            return VolleyballMatchState.SERVICE
        rally_active = self.is_rally()
        spike_action_active = self.is_spike_action()
        # [lw] The blue cue appears before the short-lived spike action glyphs.
        if self.is_spike_cue() and (rally_active or spike_action_active):
            return VolleyballMatchState.SPIKE_CUE
        if spike_action_active:
            return VolleyballMatchState.SPIKE_ACTION
        if rally_active:
            return VolleyballMatchState.RALLY
        return None

    def mark_match_state(self, match_state):
        if self._match_state == match_state:
            return
        self._match_state = match_state
        self._last_recognized_match_state = match_state
        self._unknown_state_started_at = None
        self.info_set(self.INFO_LEVEL_STATUS, self.MATCH_STATE_LABELS[match_state])
        self.log_info(f"volleyball state: {match_state.value}")

    def mark_match_state_unknown(self, now):
        if self._unknown_state_started_at is None:
            self._unknown_state_started_at = now
            self._match_state = VolleyballMatchState.UNKNOWN
            self.info_set(self.INFO_LEVEL_STATUS, self.MATCH_STATE_LABELS[self._match_state])
            self.log_info("volleyball state: unknown; continuing recognition")

        unknown_duration = now - self._unknown_state_started_at
        if unknown_duration >= self.UNKNOWN_STATE_WARNING_SECONDS and not self._unknown_state_warning_logged:
            self._unknown_state_warning_logged = True
            self.log_warning("volleyball UI is still unrecognized; continuing recognition without input")
        return unknown_duration

    def should_handle_match_end(self, now):
        if now - self._last_match_end_check_at < self.MATCH_END_CHECK_INTERVAL_SECONDS:
            return False
        self._last_match_end_check_at = now
        return True

    def handle_service(self, is_service=None):
        now = time.monotonic()
        if is_service is None:
            is_service = self.is_service()
        if not is_service:
            return self.handle_service_release()

        if self._service_phase_active:
            self.check_service_phase_timeout(now)
            return True

        self._service_phase_active = True
        self._service_phase_started_at = now
        self._service_phase_warning_logged = False
        self.log_info("new service phase")
        self.send_key("j")
        self.sleep(self.get_serve_delay())
        self.send_key("k")
        return True

    def get_serve_delay(self):
        configured_delay = self.config.get(self.CONF_SERVE_DELAY, self.DEFAULT_SERVE_DELAY)
        try:
            delay = float(configured_delay)
        except (TypeError, ValueError):
            self.log_warning(
                f"invalid serve delay {configured_delay!r}; using {self.DEFAULT_SERVE_DELAY:.1f}s"
            )
            return self.DEFAULT_SERVE_DELAY
        return max(self.MIN_SERVE_DELAY, min(delay, self.MAX_SERVE_DELAY))

    def get_play_interval(self):
        configured_interval = self.config.get(self.CONF_PLAY_INTERVAL, self.DEFAULT_PLAY_INTERVAL)
        try:
            interval = float(configured_interval)
        except (TypeError, ValueError):
            self.log_warning(
                f"invalid play interval {configured_interval!r}; using {self.DEFAULT_PLAY_INTERVAL:.1f}s"
            )
            return self.DEFAULT_PLAY_INTERVAL
        return max(self.MIN_PLAY_INTERVAL, min(interval, self.MAX_PLAY_INTERVAL))

    def handle_service_release(self):
        if not self._service_phase_active:
            return False

        self.log_info("service phase cleared")
        self.reset_service_phase()
        return False

    def check_service_phase_timeout(self, now):
        elapsed = now - self._service_phase_started_at
        if elapsed >= self.SERVICE_PHASE_WARNING_SECONDS and not self._service_phase_warning_logged:
            self._service_phase_warning_logged = True
            self.log_warning("serve UI has not cleared; continuing recognition without duplicate input")

    def reset_service_phase(self):
        self._service_phase_active = False
        self._service_phase_started_at = 0.0
        self._service_phase_warning_logged = False

    def handle_spike_cue(self):
        if self._spike_phase_active:
            return
        self._spike_phase_active = True
        self.log_info("in spike cue")
        self.wait_until(lambda: not self.is_spike_cue(), time_out=1)
        self.sleep(0.7)
        if not (self.is_rally() or self.is_spike_action()):
            self.log_warning("spike cue cleared without active volleyball controls; cancelling K")
            self.reset_spike_phase()
            return
        self.send_key("k")

    def handle_spike_action(self):
        if self._spike_phase_active:
            return
        self._spike_phase_active = True
        self.log_info("in spike action fallback")
        self.send_key("k")

    def reset_spike_phase(self):
        self._spike_phase_active = False

    def reset_match_state(self):
        self.reset_service_phase()
        self.reset_spike_phase()
        self._match_state = VolleyballMatchState.WAITING
        self._last_recognized_match_state = VolleyballMatchState.WAITING
        self._unknown_state_started_at = None
        self._unknown_state_warning_logged = False
        self._last_match_end_check_at = 0.0

    def play_once(self, key, switch_key):
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP | self.MODE_AUTO:
                position_adjust_enabled = self.config.get(
                    self.CONF_POSITION_ADJUST,
                    self.DEFAULT_POSITION_ADJUST,
                )
                if not position_adjust_enabled:
                    self._play_count = 0
                elif self._play_count >= self.POSITION_ADJUST_AFTER_HITS:
                    self.sleep(0.5)
                    self.send_key("a", down_time=0.1)
                    self.sleep(0.1)
                    self.send_key("s", down_time=0.1)
                    self._play_count = 0
                    return key, switch_key
                if self.send_key(key, interval=self.get_play_interval()):
                    if position_adjust_enabled:
                        self._play_count += 1
                    return ("j" if switch_key else "k"), not switch_key
            case self.MODE_SUP:
                pass
        return key, switch_key

    def handle_match_end(self):
        lost = self.is_match_lost()
        won = not lost and self.is_match_won()
        if not lost and not won:
            return False

        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP:
                if not (restart_box := self.get_match_end_button(next_level=False)):
                    return False
                self.handle_match_result(restart_box, won=won, next_level=False)
                return True
            case self.MODE_AUTO:
                if won:
                    self.sleep(1)
                    if self.has_three_stars():
                        if next_box := self.get_match_end_button(next_level=True):
                            self.handle_match_result(next_box, won=True, next_level=True)
                            return True
                        return False
                if not (restart_box := self.get_match_end_button(next_level=False)):
                    return False
                self.handle_match_result(restart_box, won=won, next_level=False)
                return True
            case self.MODE_SUP:
                pass
        return False

    def handle_match_result(self, box, won, next_level):
        self.reset_match_state()
        if won:
            status = "进入下一关" if next_level else "重开当前关"
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
        return all(
            self.calculate_color_percentage(
                self.STAR_GOLD_COLOR,
                self.box_of_screen(*star_roi),
            )
            >= self.STAR_GOLD_THRESHOLD
            for star_roi in self.STAR_ROIS
        )

    def get_match_end_button(self, next_level):
        if next_level:
            action_re = self.NEXT_LEVEL_ACTION_RE
        else:
            action_re = self.RESTART_ACTION_RE
        box = self.box_of_screen(*self.RESULT_ACTIONS_ROI, name="volleyball_result_actions")
        return next(iter(self.ocr(box=box, match=action_re)), None)

    def is_match_lost(self):
        return self.has_match_result(self.LOSE_TEXT_RE)

    def is_match_won(self):
        return self.has_match_result(self.WIN_TEXT_RE)

    def has_match_result(self, result_text_re):
        box = self.box_of_screen(*self.RESULT_TEXT_ROI, name="volleyball_result_text")
        return bool(self.ocr(box=box, match=result_text_re))

    def is_service(self):
        return self.are_actions_highlighted(self.SERVICE_ACTION_ROIS)

    def is_rally(self):
        return self.are_actions_highlighted(self.RALLY_ACTION_ROIS)

    def are_actions_highlighted(self, action_rois):
        from src import text_white_color

        return all(
            self.calculate_color_percentage(
                text_white_color,
                self.box_of_screen(*roi),
            )
            > self.SERVICE_ACTION_WHITE_THRESHOLD
            for roi in action_rois
        )

    def is_spike_cue(self):
        box = self.box_of_screen(0.8562, 0.8500, 0.9137, 0.9243, hcenter=True)
        return self.calculate_color_percentage(spike_bule_color, box) > 0.06

    def is_spike_action(self):
        return self.are_actions_highlighted(self.SPIKE_ACTION_ROIS)


spike_bule_color = {
    "r": (71, 100),
    "g": (155, 175),
    "b": (167, 187),
}
