import time

from ok import Logger, TriggerTask
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import FluentIcon

from src.char.CharFactory import get_char_feature_by_pos
from src.char.custom.CustomCharManager import CustomCharManager
from src.combat.BaseCombatTask import (
    BaseCombatTask,
    CharDeadException,
    CharUnavailableException,
    NotInCombatException,
    TeamChangedException,
)


class ScannerSignals(QObject):
    # Sends list of dicts: {"index": i, "feat_id": tmp_id, "mat": ndarray, "match": str|None}
    scan_done = Signal(list, str)


scanner_signals = ScannerSignals()

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    TEAM_RECHECK_INTERVAL = 1.0
    TEAM_RELOAD_WAIT_INTERVAL = 0.2

    txt_team_not_exist = "队伍不存在"
    txt_team_not_enough = "队伍人数少于2人"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": True}
        self.trigger_interval = 0.1
        self.name = "自动战斗"
        self.description = "受《异环》UI的特殊性影响, 部分场景下存在识别稳定性波动"
        self.icon = FluentIcon.CALORIES
        self.last_is_click = False
        self.default_config.update(
            {
                "自动目标": True,
                "安魂曲技能前平A(s)": 0.1,
            }
        )
        self.config_description = {
            "自动目标": "关闭时仅在中键选中敌人且画面识别到 'Lv' 文字时开启战斗",
            "安魂曲技能前平A(s)": "安魂曲放真技能前先平A出手进入交战这么久,防止开战瞬间直接放技能打空;设为0表示不补",
        }
        self.op_index = 0
        self.origin_func = {}
        self._last_team_recheck = 0.0
        if self._app is not None:
            self.tr(self.txt_team_not_exist)
            self.tr(self.txt_team_not_enough)

    def _reload_combat_team(self) -> bool:
        if self.load_chars():
            self.reset_unavailable_chars()
            self._in_combat = True
            try:
                self.switch_to_combat_start_char()
            except CharUnavailableException as e:
                logger.info(f"combat start char unavailable after team reload {e}")
            return True

        if self.chars and self.get_current_char() is not None:
            self.log_info("team reload failed, keep previous valid team")
            return True

        self.log_info("team reload pending, skip combat action this tick")
        return False

    def _reload_if_team_size_changed(self) -> bool:
        now = time.time()
        if now - self._last_team_recheck < self.TEAM_RECHECK_INTERVAL:
            return True
        self._last_team_recheck = now

        in_team, current_index, count = self.in_team()
        snapshot = self._normalize_team_snapshot(
            in_team, current_index, count, source="team size check"
        )
        if snapshot is None:
            return True
        current_index, count = snapshot
        if self.team_size == 0 or count == self.team_size:
            return True
        if count > self.team_size and not self.is_reliable_team_expansion(count):
            self.log_info(
                f"team size expansion ignored during combat {self.team_size} -> {count}"
            )
            return True

        self.log_info(f"team size changed during combat {self.team_size} -> {count}, reload chars")
        return self._reload_combat_team()

    def run(self):
        ret = False
        if not self.scene.is_in_team(self.is_in_team):
            return

        self._last_team_recheck = 0.0
        self.reset_unavailable_chars()
        combat_start = time.time()
        while self.in_combat():
            try:
                if not ret:
                    ret = True
                    self.switch_to_combat_start_char()
                if not self._reload_if_team_size_changed():
                    time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                    continue
                current_char = self.get_current_char()
                if current_char is None:
                    self.log_info("current char missing during combat, reload chars")
                    if not self._reload_combat_team():
                        time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                    continue
                current_char.perform()
            except CharDeadException:
                self.log_error("Characters dead", notify=True)
                break
            except CharUnavailableException as e:
                logger.info(
                    f"auto_combat_task_char_unavailable "
                    f"{int(time.time() - combat_start)} {e}"
                )
                continue
            except TeamChangedException as e:
                logger.info(f"auto_combat_task_team_changed {int(time.time() - combat_start)} {e}")
                if not self._reload_combat_team():
                    time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                continue
            except NotInCombatException as e:
                logger.info(f"auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}")
                break
        if ret:
            self.combat_end()

    def scan_team(self):
        self.log_info("开始扫描当前队伍...")
        in_team, _, count = self.in_team()
        if not in_team or count == 0:
            scanner_signals.scan_done.emit([], self.tr(self.txt_team_not_exist))
            self.log_info("队伍不存在, 扫描结束")
            return
        if count < 2:
            scanner_signals.scan_done.emit([], self.tr(self.txt_team_not_enough))
            self.log_info("队伍人数少于2人, 扫描结束")
            return

        manager = CustomCharManager()
        results = []
        frame = self.frame
        for i in range(count):
            feature_mat, w, h = get_char_feature_by_pos(self, i, frame=frame)
            if feature_mat is not None and feature_mat.size > 0:
                is_match, match_name, confidence = manager.match_feature(self, feature_mat)
                name = match_name if is_match else None
                results.append(
                    {"index": i, "mat": feature_mat, "width": w, "height": h, "match": name}
                )
                self.log_debug(f"char_{i + 1}: {name}, confidence={confidence:.2f}")
        scanner_signals.scan_done.emit(results, "")
        self.log_info("扫描完成！")
