import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from src.config import config
from src.lw import abyss_ext as ax
from src.tasks.AbyssTask import AbyssTask

W, H = 2000, 1125


def text(name, cx, cy, width=0.06, height=0.03):
    w, h = width * W, height * H
    return SimpleNamespace(name=name, x=cx * W - w / 2, y=cy * H - h / 2, width=w, height=h)


def station_frame(label_boxes_and_stars):
    frame = np.full((H, W, 3), 40, dtype=np.uint8)
    for box, stars in label_boxes_and_stars:
        cx = box.x + box.width / 2
        cy = box.y + box.height / 2 + ax.STAR_SLOT_DY * H
        for index, dx in enumerate(ax.STAR_SLOT_DX):
            if index >= stars:
                continue
            x = int(cx + dx * W)
            frame[int(cy) - 10:int(cy) + 10, x - 10:x + 10] = (30, 200, 240)  # BGR gold
    return frame


class TestAbyssParsing(unittest.TestCase):
    def test_chinese_station_numbers(self):
        self.assertEqual(ax.parse_cn_number("八"), 8)
        self.assertEqual(ax.parse_cn_number("十"), 10)
        self.assertEqual(ax.parse_cn_number("十二"), 12)
        self.assertEqual(ax.parse_cn_number("二十一"), 21)
        self.assertEqual(ax.parse_cn_number("08"), 8)
        self.assertIsNone(ax.parse_cn_number("站"))

    def test_hud_reads_half_and_waves_including_missing_slash(self):
        hud = ax.parse_hud([SimpleNamespace(name="第八站下行线"), SimpleNamespace(name="怪物波次"),
                            SimpleNamespace(name="1/1")])
        self.assertEqual(hud, ax.AbyssHud(8, ax.HALF_LOWER, (1, 1)))
        self.assertTrue(hud.finished)

        upper = ax.parse_hud([SimpleNamespace(name="第八站上行线"), SimpleNamespace(name="怪物波次"),
                              SimpleNamespace(name="01")])
        self.assertEqual(upper, ax.AbyssHud(8, ax.HALF_UPPER, (0, 1)))
        self.assertFalse(upper.finished)
        self.assertIsNone(ax.parse_hud([SimpleNamespace(name="08:31")]))

    def test_routes_pair_seals_with_buttons_and_skip_full_route(self):
        texts = [
            text("节理环线当前站序10/10", 0.214, 0.248),
            text("印鉴收集30/30", 0.896, 0.249),
            text("前往", 0.901, 0.301),
            text("星流环线当前站序7/12", 0.21, 0.378),
            text("印鉴收集", 0.87, 0.38),
            text("21/36", 0.92, 0.38),
            text("前往", 0.901, 0.432),
        ]
        routes = ax.parse_routes(texts)
        self.assertEqual([(r.seals, r.total) for r in routes], [(30, 30), (21, 36)])
        chosen = ax.select_route(routes)
        self.assertIs(chosen.go_button, texts[6])
        self.assertEqual(chosen.station_count, 12)
        self.assertIsNone(ax.select_route(routes[:1]))

    def test_station_cards_count_gold_medals_and_pick_first_unfinished(self):
        labels = [text("第六站", 0.888, 0.479), text("第七站", 0.888, 0.618),
                  text("第八站", 0.888, 0.756)]
        frame = station_frame([(labels[0], 3), (labels[1], 3), (labels[2], 0)])
        cards = ax.parse_station_cards(labels, frame)
        self.assertEqual([(c.number, c.stars) for c in cards], [(6, 3), (7, 3), (8, 0)])
        self.assertEqual(ax.select_station(cards).number, 8)

    def test_partially_starred_card_is_unfinished_and_cut_off_card_is_unknown(self):
        partial = text("第五站", 0.888, 0.34)
        cut_off = text("第九站", 0.888, 0.84)
        frame = station_frame([(partial, 2)])
        cards = ax.parse_station_cards([partial, cut_off], frame)
        self.assertEqual([(c.number, c.stars) for c in cards], [(5, 2), (9, None)])
        self.assertEqual(ax.select_station(cards).number, 5)
        self.assertIsNone(ax.select_station([cards[1]]))

    def test_hud_checks_count_pink_marks(self):
        frame = np.full((H, W, 3), 20, dtype=np.uint8)
        self.assertEqual(ax.count_hud_checks(frame), 0)
        for row in ax.HUD_CHECK_ROWS[:2]:
            y = int(row * H)
            frame[y - 12:y + 12, 350:374] = (150, 90, 255)  # BGR pink
        self.assertEqual(ax.count_hud_checks(frame), 2)

    def test_defeat_check_clears_lower_half_when_wave_counter_is_misread(self):
        frame = np.full((H, W, 3), 20, dtype=np.uint8)
        misread = ax.AbyssHud(8, ax.HALF_LOWER, None)
        self.assertFalse(ax.station_cleared(misread, frame))
        y = int(ax.HUD_CHECK_ROWS[0] * H)
        frame[y - 12:y + 12, 290:314] = (150, 90, 255)
        self.assertTrue(ax.station_cleared(misread, frame))
        self.assertFalse(ax.station_cleared(ax.AbyssHud(8, ax.HALF_UPPER, None), frame))
        full_waves = ax.AbyssHud(8, ax.HALF_LOWER, (1, 1))
        self.assertTrue(ax.station_cleared(full_waves, np.zeros_like(frame)))

    def test_station_exit_policy(self):
        options = {ax.EXIT_NEXT: 1, ax.EXIT_REPLAY: 2, ax.EXIT_END: 3}
        self.assertEqual(ax.choose_station_exit(2, 0, 2, 8, 12, options), ax.EXIT_REPLAY)
        self.assertEqual(ax.choose_station_exit(2, 2, 2, 8, 12, options), ax.EXIT_NEXT)
        self.assertEqual(ax.choose_station_exit(3, 0, 2, 8, 12, options), ax.EXIT_NEXT)
        self.assertEqual(ax.choose_station_exit(3, 0, 2, 12, 12, options), ax.EXIT_END)
        self.assertEqual(ax.choose_station_exit(3, 0, 2, 8, 0, {ax.EXIT_END: 3}), ax.EXIT_END)
        self.assertIsNone(ax.choose_station_exit(3, 0, 2, 8, 12, {}))

    def test_dialog_options_ignore_trailing_punctuation(self):
        options = ax.parse_dialog_options(
            [SimpleNamespace(name="去下一站。"), SimpleNamespace(name="再次游览。"),
             SimpleNamespace(name="结束行程。")]
        )
        self.assertEqual(set(options), {ax.EXIT_NEXT, ax.EXIT_REPLAY, ax.EXIT_END})


class FakeStationTask(ax.AbyssTaskMixin):
    UPPER_TRANSITION_TIMEOUT = 0

    def __init__(self, huds, combat_results):
        self.config = {self.CONF_COMBAT_WAIT: 8, self.CONF_MAX_RESTARTS: 1}
        self.huds = list(huds)
        self.walk_until_combat = Mock(side_effect=list(combat_results))
        self.abyss_fight = Mock()
        self.abyss_restart_half = Mock()
        self.abyss_close_popup = Mock(return_value=False)
        self.in_combat = Mock(return_value=False)
        self.is_in_team = Mock(return_value=True)
        self.info_set = Mock()
        self.log_warning = Mock()
        self.sleep = Mock()
        self.frame = np.full((H, W, 3), 20, dtype=np.uint8)

    def abyss_read_hud(self, frame=None):
        return self.huds.pop(0)


class TestAbyssStationLoop(unittest.TestCase):
    def test_no_combat_within_wait_restarts_half_then_fights_both_halves(self):
        upper = ax.AbyssHud(8, ax.HALF_UPPER, (0, 1))
        lower = ax.AbyssHud(8, ax.HALF_LOWER, (0, 1))
        done = ax.AbyssHud(8, ax.HALF_LOWER, (1, 1))
        task = FakeStationTask([upper, upper, lower, done], [False, True, True])

        self.assertEqual(task.abyss_play_station(), done)
        task.walk_until_combat.assert_called_with(time_out=8.0, run=True)
        self.assertEqual(task.abyss_restart_half.call_count, 1)
        self.assertEqual(task.abyss_fight.call_count, 2)

    def test_restart_budget_is_per_half_and_aborts_when_exceeded(self):
        upper = ax.AbyssHud(8, ax.HALF_UPPER, (0, 1))
        task = FakeStationTask([upper, upper, upper], [False, False])
        with self.assertRaises(ax.AbyssAbort):
            task.abyss_play_station()
        self.assertEqual(task.abyss_restart_half.call_count, 1)

    def test_cleared_upper_half_waits_for_transition_without_walking(self):
        task = FakeStationTask(
            [ax.AbyssHud(8, ax.HALF_UPPER, (1, 1)), ax.AbyssHud(8, ax.HALF_LOWER, (1, 1))], []
        )
        task.UPPER_TRANSITION_TIMEOUT = 60
        self.assertTrue(task.abyss_play_station().finished)
        task.walk_until_combat.assert_not_called()


class TestAbyssRegistration(unittest.TestCase):
    def test_registered_right_after_volleyball(self):
        tasks = [tuple(item) for item in config["onetime_tasks"]]
        index = tasks.index(("src.tasks.VolleyballTask", "VolleyballTask"))
        self.assertEqual(tasks[index + 1], ("src.tasks.AbyssTask", "AbyssTask"))

    def test_task_uses_abyss_mixin_and_owns_use_ult_key(self):
        self.assertTrue(issubclass(AbyssTask, ax.AbyssTaskMixin))
        self.assertEqual(AbyssTask.CONF_USE_ULT, "使用终结技")


if __name__ == "__main__":
    unittest.main()
