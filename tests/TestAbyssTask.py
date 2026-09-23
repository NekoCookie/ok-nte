import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_seal_fraction_recovers_misread_or_missing_slash(self):
        self.assertEqual(ax.parse_seal_fraction("27/36"), (27, 36))
        self.assertEqual(ax.parse_seal_fraction("27136"), (27, 36))  # real OCR of "27 / 36"
        self.assertEqual(ax.parse_seal_fraction("30130"), (30, 30))
        self.assertEqual(ax.parse_seal_fraction("21136"), (21, 36))
        self.assertEqual(ax.parse_seal_fraction("27l36"), (27, 36))
        self.assertEqual(ax.parse_seal_fraction("2736"), (27, 36))
        self.assertIsNone(ax.parse_seal_fraction("36/27"))
        self.assertIsNone(ax.parse_seal_fraction(""))

    def test_misread_slash_row_is_not_dropped_as_full(self):
        texts = [
            text("印鉴收集30/30", 0.896, 0.249), text("前往", 0.901, 0.301),
            text("印鉴收集27136", 0.897, 0.38), text("前往", 0.901, 0.432),
        ]
        routes = ax.parse_routes(texts)
        self.assertEqual([(r.seals, r.total) for r in routes], [(30, 30), (27, 36)])
        self.assertEqual(ax.select_route(routes).seals, 27)

    def test_unread_route_row_blocks_the_all_full_conclusion(self):
        task = object.__new__(ax.AbyssTaskMixin)
        task._abyss_ocr = lambda roi, match=None, frame=None: [
            text("印鉴收集30/30", 0.896, 0.249), text("前往", 0.901, 0.301),
            text("印鉴收集??", 0.897, 0.38), text("前往", 0.901, 0.432),
        ]
        self.assertIsNone(task._abyss_read_routes())
        routes, unread = task._abyss_last_route_read
        self.assertEqual((len(routes), unread), (1, 1))

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

    def test_terminal_station_hud_and_card(self):
        # Real OCR of the supplied last-station HUD: "终点站", "下行线", "怪物波次", "11".
        hud = ax.parse_hud([SimpleNamespace(name=n) for n in ("终点站", "下行线", "怪物波次", "11")])
        self.assertEqual(hud, ax.AbyssHud(ax.TERMINAL_STATION, ax.HALF_LOWER, (1, 1)))
        self.assertEqual(ax.station_label(hud.station), "终点站")

        labels = [text("第十一站", 0.888, 0.479), text("终点站", 0.888, 0.618)]
        frame = station_frame([(labels[0], 3), (labels[1], 0)])
        cards = ax.parse_station_cards(labels, frame)
        self.assertEqual([(c.number, c.stars) for c in cards], [(11, 3), (ax.TERMINAL_STATION, 0)])
        self.assertEqual(ax.select_station(cards).number, ax.TERMINAL_STATION)

    def test_terminal_station_ends_trip_even_without_route_count(self):
        options = {ax.EXIT_NEXT: 1, ax.EXIT_REPLAY: 2, ax.EXIT_END: 3}
        self.assertEqual(
            ax.choose_station_exit(3, 0, 2, ax.TERMINAL_STATION, 0, options), ax.EXIT_END
        )

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
        self.abyss_walk_until_combat = Mock(side_effect=list(combat_results))
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
        task.abyss_walk_until_combat.assert_called_with(8.0)
        self.assertEqual(task.abyss_restart_half.call_count, 1)
        self.assertEqual(task.abyss_fight.call_count, 2)

    def test_restart_budget_is_per_half_and_aborts_when_exceeded(self):
        upper = ax.AbyssHud(8, ax.HALF_UPPER, (0, 1))
        task = FakeStationTask([upper, upper, upper], [False, False])
        with self.assertRaises(ax.AbyssAbort):
            task.abyss_play_station()
        self.assertEqual(task.abyss_restart_half.call_count, 1)

    def test_next_station_detail_page_is_started_before_fighting(self):
        start = text("开始挑战", 0.879, 0.915)
        done = ax.AbyssHud(10, ax.HALF_LOWER, (1, 1))
        task = FakeStationTask([done], [])
        task.is_in_team = Mock(side_effect=[False, True])
        task._abyss_ocr = Mock(side_effect=lambda roi, match=None, frame=None: (
            [start] if match is ax.START_RE else []))
        task.operate_click = Mock()
        task.log_info = Mock()

        self.assertEqual(task.abyss_play_station(), done)
        task.operate_click.assert_called_once_with(start, action_name="abyss_start", interval=2)

    def test_cleared_upper_half_waits_for_transition_without_walking(self):
        task = FakeStationTask(
            [ax.AbyssHud(8, ax.HALF_UPPER, (1, 1)), ax.AbyssHud(8, ax.HALF_LOWER, (1, 1))], []
        )
        task.UPPER_TRANSITION_TIMEOUT = 60
        self.assertTrue(task.abyss_play_station().finished)
        task.abyss_walk_until_combat.assert_not_called()


class MenuTask(ax.AbyssTaskMixin):
    width, height = W, H

    def __init__(self, menu_open, caption_clicks_work=False):
        self.menu_open = menu_open
        # Captions from the supplied 2000x1125 ESC-menu screenshot.
        self.continue_button = text("继续挑战", 0.236, 0.596, width=0.05)
        self.restart_button = text("重启当前半场", 0.411, 0.596, width=0.075)
        self.caption_clicks_work = caption_clicks_work
        self.operate_click = Mock(side_effect=self._click)
        self.send_key = Mock(side_effect=lambda *a, **k: setattr(self, "menu_open", True))
        self.wait_in_team = Mock()
        self.ensure_main = Mock()
        self.log_info = Mock()

    def _click(self, *args, **kwargs):
        # Only the round icon above the caption reacts in the game.
        x, y = args
        if y < 0.5 or self.caption_clicks_work:
            self.menu_open = False

    def wait_until(self, condition, pre_action=None, time_out=0, settle_time=0):
        for _ in range(3):
            if pre_action:
                pre_action()
            if result := condition():
                return result
        return None

    def _abyss_ocr(self, roi, match=None, frame=None):
        if not self.menu_open:
            return []
        return [self.continue_button if match is ax.CONTINUE_RE else self.restart_button]


class TestAbyssStartStates(unittest.TestCase):
    def test_start_on_stage_esc_menu_clicks_continue_icon_not_caption(self):
        task = MenuTask(menu_open=True)
        task.abyss_prepare_start()
        (x, y), _ = task.operate_click.call_args
        self.assertAlmostEqual(x, 0.236, places=3)
        self.assertAlmostEqual(y, 0.596 - ax.AbyssTaskMixin.ESC_MENU_ICON_DY, places=3)
        self.assertFalse(task.menu_open)
        task.ensure_main.assert_called_once()

    def test_restart_icon_click_is_verified_by_menu_closing(self):
        task = MenuTask(menu_open=True)
        self.assertTrue(task._abyss_click_menu_entry(ax.RESTART_HALF_RE))
        (x, y), _ = task.operate_click.call_args
        self.assertAlmostEqual(x, 0.411, places=3)
        self.assertLess(y, 0.5)

    def test_start_without_menu_only_returns_to_main(self):
        task = MenuTask(menu_open=False)
        task.abyss_prepare_start()
        task.operate_click.assert_not_called()
        task.ensure_main.assert_called_once()

    def test_restart_does_not_toggle_an_already_open_menu_closed(self):
        task = MenuTask(menu_open=True)
        task._abyss_open_stage_menu()
        task.send_key.assert_not_called()
        task.menu_open = False
        task._abyss_open_stage_menu()
        task.send_key.assert_called_once()


class WalkTask(ax.AbyssTaskMixin):
    WALK_POLL_INTERVAL = 0

    def __init__(self, popups, combat_after):
        self.popups = list(popups)
        self.polls = 0
        self.combat_after = combat_after
        self.middle_click = Mock()
        self.send_key_down = Mock()
        self.send_key_up = Mock()
        self.send_key = Mock()
        self.sleep = Mock()

    def in_combat(self):
        self.polls += 1
        return self.polls > self.combat_after

    def abyss_close_popup(self):
        return self.popups.pop(0) if self.popups else False


class TestAbyssWalk(unittest.TestCase):
    def test_popup_mid_walk_releases_w_then_resumes_until_combat(self):
        task = WalkTask(popups=[False, True], combat_after=4)
        self.assertTrue(task.abyss_walk_until_combat(8))
        self.assertEqual(task.send_key_down.call_count, 2)
        self.assertEqual(task.send_key_up.call_count, 2)

    def test_timeout_without_combat_releases_w(self):
        task = WalkTask(popups=[], combat_after=10**9)
        with patch.object(ax.time, "time", side_effect=[0, 0, 1, 99]):
            self.assertFalse(task.abyss_walk_until_combat(8))
        task.send_key_up.assert_called_once_with("w")


class TravelTask(ax.AbyssTaskMixin):
    def __init__(self, travel_visible, in_team=False, interac=False):
        self.travel = [text("传送", 0.858, 0.893)] if travel_visible else []
        self.is_in_team = Mock(return_value=in_team)
        self.find_interac = Mock(return_value=interac)
        self.operate_click = Mock()
        self.send_key = Mock()
        self.log_info = Mock()

    def _abyss_ocr(self, roi, match=None, frame=None):
        return self.travel if match is ax.TRAVEL_RE else []


class TestAbyssTravel(unittest.TestCase):
    def test_map_teleport_button_is_clicked_before_station_list(self):
        task = TravelTask(travel_visible=True)
        task._abyss_advance_to_station_list()
        task.operate_click.assert_called_once_with(
            task.travel[0], action_name="abyss_travel", interval=3
        )

    def test_entrance_interaction_after_teleport(self):
        task = TravelTask(travel_visible=False, in_team=True, interac=True)
        task._abyss_advance_to_station_list()
        task.send_key.assert_called_once_with("f", action_name="abyss_entry", interval=3)
        task.operate_click.assert_not_called()


class LeaveTask(ax.AbyssTaskMixin):
    def __init__(self, hud, in_team=True, start_visible=False):
        self.hud = hud
        self.is_in_team = Mock(return_value=in_team)
        self.start_visible = start_visible

    def abyss_read_hud(self, frame=None):
        return self.hud

    def _abyss_ocr(self, roi, match=None, frame=None):
        return [text("开始挑战", 0.879, 0.915)] if self.start_visible else []


class TestAbyssLeaveStation(unittest.TestCase):
    def test_stale_old_stage_without_objectives_is_not_a_new_stage(self):
        # Real failure: 4s after "去下一站" the old HUD still read "第10站 下行线" with
        # objectives hidden, the loop walked for 8s and restarted the cleared half.
        stale = LeaveTask(ax.AbyssHud(10, ax.HALF_LOWER, None))
        self.assertFalse(stale._abyss_left_station(ax.EXIT_NEXT, 10))
        self.assertFalse(stale._abyss_left_station(ax.EXIT_REPLAY, 10))

    def test_next_station_requires_a_new_station_number(self):
        same = LeaveTask(ax.AbyssHud(10, ax.HALF_UPPER, (0, 1)))
        self.assertFalse(same._abyss_left_station(ax.EXIT_NEXT, 10))
        nxt = LeaveTask(ax.AbyssHud(11, ax.HALF_UPPER, (0, 1)))
        self.assertTrue(nxt._abyss_left_station(ax.EXIT_NEXT, 10))

    def test_replay_accepts_restarted_upper_half_and_detail_page(self):
        self.assertTrue(
            LeaveTask(ax.AbyssHud(10, ax.HALF_UPPER, (0, 1)))._abyss_left_station(
                ax.EXIT_REPLAY, 10
            )
        )
        detail = LeaveTask(None, in_team=False, start_visible=True)
        self.assertTrue(detail._abyss_left_station(ax.EXIT_NEXT, 10))


def record_frame(old, new):
    frame = np.full((H, W, 3), 30, dtype=np.uint8)
    y = int(ax.RECORD_STARS_Y * H)
    for xs, count in ((ax.RECORD_OLD_STARS_X, old), (ax.RECORD_NEW_STARS_X, new)):
        for x in xs[:count]:
            cx = int(x * W)
            frame[y - 10:y + 10, cx - 10:cx + 10] = (30, 200, 240)
    return frame


class RecordTask(ax.AbyssTaskMixin):
    def __init__(self, frame):
        self.frame = frame
        self.open = True
        self.clicked = []
        self.log_info = Mock()

    def _abyss_ocr(self, roi, match=None, frame=None):
        if not self.open:
            return []
        if match is ax.RECORD_TITLE_RE:
            return [text("确认记录", 0.5, 0.122)]
        if match is ax.RECORD_CONFIRM_RE:
            return [text("确认", 0.586, 0.797)]
        if match is ax.RECORD_CANCEL_RE:
            return [text("取消", 0.414, 0.797)]
        return []

    def operate_click(self, box, **kwargs):
        self.clicked.append(box.name)
        self.open = False

    def wait_until(self, condition, pre_action=None, time_out=0, settle_time=0):
        for _ in range(3):
            if pre_action:
                pre_action()
            if result := condition():
                return result
        return None


class TestAbyssRecordPrompt(unittest.TestCase):
    def test_equal_record_keeps_the_original(self):
        task = RecordTask(record_frame(3, 3))  # the supplied 3-star vs 3-star prompt
        self.assertTrue(task.abyss_handle_record_prompt())
        self.assertEqual(task.clicked, ["取消"])

    def test_better_record_overwrites(self):
        task = RecordTask(record_frame(1, 3))
        task.abyss_handle_record_prompt()
        self.assertEqual(task.clicked, ["确认"])

    def test_no_prompt_is_a_no_op(self):
        task = RecordTask(record_frame(0, 0))
        task.open = False
        self.assertFalse(task.abyss_handle_record_prompt())
        self.assertEqual(task.clicked, [])


class NpcTask(ax.AbyssTaskMixin):
    def __init__(self, texts):
        self.texts = texts

    def _abyss_ocr(self, roi, match=None, frame=None):
        return self.texts


class TestAbyssFindNpc(unittest.TestCase):
    def test_far_npc_is_found_by_distance_marker(self):
        # Real OCR of the supplied far view: timer, a building sign and the "25m" marker.
        marker = text("25m", 0.608, 0.358)
        task = NpcTask([text("m07:41", 0.485, 0.156), text("银行", 0.514, 0.18), marker])
        self.assertIs(task.abyss_find_npc(), marker)

    def test_name_is_preferred_over_distance_marker(self):
        name = text("浮游小姐2001号", 0.407, 0.396)
        task = NpcTask([text("12m", 0.6, 0.3), name])
        self.assertIs(task.abyss_find_npc(), name)

    def test_timer_is_not_a_distance_marker(self):
        self.assertIsNone(NpcTask([text("08:31", 0.505, 0.156)]).abyss_find_npc())


class RewardTask(ax.AbyssTaskMixin):
    width, height = W, H

    def __init__(self, claimable=3, overlay_after_claim=False, panel_opens=True):
        self.claimable = claimable
        self.overlay_after_claim = overlay_after_claim
        self.panel_opens = panel_opens
        self.panel = False
        self.overlay = False
        self.clicks = []
        self.log_info = Mock()
        self.log_warning = Mock()

    def _abyss_ocr(self, roi, match=None, frame=None):
        if roi == self.SEAL_COUNT_ROI:
            return [text("36136", 0.904, 0.199)]  # real OCR of "36/36" on the station page
        if roi == self.ROUTE_LIST_ROI:
            names = ("全日路线", "节理环线", "特别路线", "8天2小时", "星流环线")
            found = [text(n, 0.06, 0.2 + i * 0.07) for i, n in enumerate(names)]
            return [t for t in found if match is None or match.search(t.name)]
        visible = self.panel and not self.overlay
        if match is ax.REWARD_PANEL_RE:
            return [text("累计获得", 0.222, 0.242)] if visible else []
        if match is ax.CLAIM_RE:
            return [text("领取", 0.785, 0.269)] if visible and self.claimable else []
        return []

    def operate_click(self, *args, **kwargs):
        if len(args) == 2:
            point = (round(args[0], 3), round(args[1], 3))
            self.clicks.append(point)
            if point == tuple(round(v, 3) for v in ax.AbyssTaskMixin.REWARD_CLOSE):
                self.panel = False
            elif point == ax.AbyssTaskMixin.REWARD_OVERLAY_DISMISS:
                self.overlay = False
            elif self.panel_opens:
                self.panel = True
            return
        self.clicks.append(args[0].name)
        if args[0].name == "领取":
            self.claimable -= 1
            self.overlay = self.overlay_after_claim

    def wait_until(self, condition, pre_action=None, time_out=0, settle_time=0):
        for _ in range(3):
            if pre_action:
                pre_action()
            if result := condition():
                return result
        return None


class TestAbyssSealRewards(unittest.TestCase):
    def test_book_icon_is_above_the_misread_seal_count(self):
        task = RewardTask(claimable=0)
        task._abyss_click_reward_icon()
        x, y = task.clicks[0]
        self.assertAlmostEqual(x, 0.904, places=3)
        self.assertAlmostEqual(y, 0.199 - ax.AbyssTaskMixin.REWARD_ICON_DY, places=3)

    def test_claims_every_available_milestone_then_closes(self):
        task = RewardTask(claimable=3)  # the supplied panel: 30, 33 and 36 claimable
        self.assertEqual(task.abyss_claim_seal_rewards(), 3)
        self.assertEqual(task.clicks.count("领取"), 3)
        self.assertFalse(task.panel)

    def test_obtained_overlay_is_dismissed_between_claims(self):
        task = RewardTask(claimable=2, overlay_after_claim=True)
        self.assertEqual(task.abyss_claim_seal_rewards(), 2)
        self.assertIn(ax.AbyssTaskMixin.REWARD_OVERLAY_DISMISS, task.clicks)

    def test_panel_that_never_opens_is_skipped_without_error(self):
        task = RewardTask(panel_opens=False)
        self.assertEqual(task.abyss_claim_seal_rewards(), 0)
        task.log_warning.assert_called_once()

    def test_every_route_card_is_visited_and_headers_are_ignored(self):
        task = RewardTask(claimable=1)
        task.abyss_claim_all_route_rewards()
        self.assertIn("节理环线", task.clicks)
        self.assertIn("星流环线", task.clicks)
        self.assertNotIn("全日路线", task.clicks)
        self.assertNotIn("特别路线", task.clicks)


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
