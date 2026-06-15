import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from ok import Box

from src.Labels import Labels
from src.utils import game_filters as gf
from src.utils import image_utils as iu

if TYPE_CHECKING:
    from src.tasks.BaseNTETask import BaseNTETask

    _TaskProxy = BaseNTETask
else:

    class _TaskProxy:
        pass


@dataclass
class _CurrentCharDetection:
    index: int
    score: float
    scores: list[float]
    accepted: bool
    strong: bool
    reason: str
    raw_scores: list[float]
    core_scores: list[float] | None


class CharUIMixin(_TaskProxy):
    CURRENT_CHAR_REJECT_SCORE = 0.75
    CURRENT_CHAR_ACCEPT_SCORE = 0.45
    CURRENT_CHAR_RAW_CANDIDATE_SCORE = 0.85
    CURRENT_CHAR_RAW_CANDIDATE_MARGIN = 0.06
    CURRENT_CHAR_RAW_STRONG_SCORE = 0.45
    CURRENT_CHAR_RAW_STRONG_MARGIN = 0.15
    CURRENT_CHAR_CORE_STRONG_SCORE = 0.70
    CURRENT_CHAR_CORE_STRONG_MARGIN = 0.08
    CURRENT_CHAR_STICKY_SECONDS = 0.8
    CURRENT_CHAR_STABLE_ACCEPT_REASONS = {"raw_core_agree", "core_strong", "raw_strong"}

    # 下场角色头像右侧的"大招就绪菱形"格:大招随充能"渐显",菱形越亮 lap 越高。
    # 实战实测:真满(能放出)lap>18000,快满未满(放不出)lap 12000~16500,没满<7000。
    # 用边缘能量(Laplacian 方差)判:≥PRESENT 才算真满(避免快满误切空放);
    # ≤ABSENT 算没满;中间是"快满未满"返回 None(不当大招,回退原逻辑,不切)。
    # 坐标实测自 2560x1440(slot1 菱形格 x2440 y312 32x32),按角色竖直间距复制到各槽。
    ULT_DIAMOND_X = 2440
    ULT_DIAMOND_Y = 312
    ULT_DIAMOND_SIZE = 32
    ULT_DIAMOND_LAP_PRESENT = 17000
    ULT_DIAMOND_LAP_ABSENT = 8000

    def _init_char_ui_state(self):
        self._char_ui_offset = False
        self._current_char_tracker = {
            "index": -1,
            "score": 1.0,
            "time": 0,
            "reason": "",
        }

    def _get_char_text_box(self, index: int):
        box = self.get_box_by_name(f"char_{index + 1}_text")
        return box

    def get_base_char_element_box(self):
        box = self.box_of_screen_scaled(
            2560, 1440, 2438, 335, width_original=29, height_original=29
        )
        box = self._shift_char_ui_box(box, expend=True)
        return box

    def get_ultimate_diamond_box(self, index: int) -> Box:
        """第 index 个角色头像右侧"大招就绪菱形"格的区域框(随分辨率缩放、跟 UI 偏移)。"""
        box = self.box_of_screen_scaled(
            2560,
            1440,
            self.ULT_DIAMOND_X,
            self.ULT_DIAMOND_Y,
            width_original=self.ULT_DIAMOND_SIZE,
            height_original=self.ULT_DIAMOND_SIZE,
        )
        if self._char_ui_offset:
            box = self._shift_char_ui_box(box)
        return self.get_box_by_char_spacing(box, index)

    def off_field_ultimate_ready(self, index: int, frame=None):
        """看下场角色头像的元素菱形是否亮起 => 大招就绪。

        菱形是硬描边几何图标(高边缘能量),没大招时该格是空背景/头像光晕(平滑、低边缘能量),
        用 Laplacian 方差区分,属性无关、亮/暗背景通吃。返回 True(就绪)/ False(未就绪)/
        None(介于阈值之间不确定,或裁帧失败 —— 调用方回退到原时间推算)。
        """
        try:
            if frame is None:
                frame = self.frame
            if frame is None:
                return None
            crop = self.get_ultimate_diamond_box(index).crop_frame(frame)
            if crop is None or crop.size == 0:
                return None
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F, ksize=3).var())
            if lap_var >= self.ULT_DIAMOND_LAP_PRESENT:
                result = True
            elif lap_var <= self.ULT_DIAMOND_LAP_ABSENT:
                result = False
            else:
                result = None
            # 诊断日志:每角色每秒最多一条,便于验证识别准度/调阈值(验证稳后可删)
            log_times = getattr(self, "_ult_diamond_log_times", None)
            if log_times is None:
                log_times = {}
                self._ult_diamond_log_times = log_times
            now = time.time()
            if now - log_times.get(index, 0) > 1.0:
                log_times[index] = now
                self.log_info(f"ult diamond char{index + 1} lap={lap_var:.0f} -> {result}")
            return result
        except Exception as e:
            self.log_debug(f"off_field_ultimate_ready failed: {e}")
            return None

    def _shift_char_ui_box(self, box: Box, expend=False):
        offset = -9 * self.width / 2560
        width_offset = 0
        if expend:
            width_offset = -offset
        box = box.copy(x_offset=offset, width_offset=width_offset)
        return box

    @property
    def _char_vertical_spacing(self):
        return int(self.height * 176 / 1440)

    def get_box_by_char_spacing(self, box: Box, index: int):
        return box.copy(y_offset=index * self._char_vertical_spacing, name=f"{box.name}_{index}")

    def _get_char_template_data(self):
        if (
            not hasattr(self, "_char_template_cache")
            or self._char_template_cache.get("width") != self.width
            or self._char_template_cache.get("height") != self.height
        ):
            feature = self.get_feature_by_name(Labels.is_current_char)
            mat = feature.mat
            if len(mat.shape) == 3 and mat.shape[2] != 2:
                mat = gf.current_char_filter(mat)
            self._char_template_cache = {
                "width": self.width,
                "height": self.height,
                "mat": mat,
            }

        return self._char_template_cache["mat"]

    def _match_current_char_feature(self, current_mat, template_mat):
        th, tw = template_mat.shape[:2]
        ch, cw = current_mat.shape[:2]
        if ch < th or cw < tw:
            return 1.0

        result = cv2.matchTemplate(current_mat, template_mat, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if np.isnan(max_val):
            return 1.0
        return 1.0 - max_val

    def _get_current_char_core_scores(self, frame, template_mat, base_box):
        """Match the stable inner part of the current-character marker."""
        tpl_x, tpl_y, width, height = 6, 3, 20, 21
        frame_x, frame_y = 15, 3

        template_slice = template_mat[tpl_y : tpl_y + height, tpl_x : tpl_x + width]
        if template_slice.shape[0] < 8 or template_slice.shape[1] < 12:
            return None

        scores = []
        for i in range(4):
            box = self.get_box_by_char_spacing(base_box, i)
            current_mat = gf.current_char_filter(box.crop_frame(frame))
            marker_slice = current_mat[
                frame_y : frame_y + height,
                frame_x : frame_x + width,
            ]
            scores.append(self._match_current_char_feature(marker_slice, template_slice))
        return scores

    def _build_current_char_scores(self, index, score, accepted):
        scores = [self.CURRENT_CHAR_REJECT_SCORE] * 4
        if accepted and 0 <= index < len(scores):
            scores[index] = min(score, self.CURRENT_CHAR_ACCEPT_SCORE)
        return scores

    def _rank_current_char_scores(self, scores):
        if not scores:
            return -1, 1.0, 0.0
        best_idx = int(np.argmin(scores))
        ordered_scores = sorted(scores)
        best_score = ordered_scores[0]
        second_score = ordered_scores[1] if len(ordered_scores) > 1 else 1.0
        return best_idx, best_score, second_score - best_score

    def _get_current_char_boxes(self):
        base_box = self.get_box_by_name(Labels.is_current_char)
        base_box = self._shift_char_ui_box(base_box, expend=True)
        return base_box, [self.get_box_by_char_spacing(base_box, i) for i in range(4)]

    def _detect_current_char_once(self, frame=None):
        if frame is None:
            frame = self.frame
        if frame is None:
            return _CurrentCharDetection(
                index=-1,
                score=1.0,
                scores=[self.CURRENT_CHAR_REJECT_SCORE] * 4,
                accepted=False,
                strong=False,
                reason="empty_frame",
                raw_scores=[1.0] * 4,
                core_scores=None,
            )

        template_mat = self._get_char_template_data()
        base_box, boxes = self._get_current_char_boxes()
        raw_scores = []
        for box in boxes:
            current_mat = gf.current_char_filter(box.crop_frame(frame))
            raw_scores.append(self._match_current_char_feature(current_mat, template_mat))

        raw_idx, raw_score, raw_margin = self._rank_current_char_scores(raw_scores)
        core_scores = self._get_current_char_core_scores(frame, template_mat, base_box)
        core_idx, core_score, core_margin = self._rank_current_char_scores(core_scores or [])

        index = raw_idx
        score = 1.0
        accepted = False
        strong = False
        reason = "rejected"

        raw_candidate = (
            raw_score <= self.CURRENT_CHAR_RAW_CANDIDATE_SCORE
            and raw_margin >= self.CURRENT_CHAR_RAW_CANDIDATE_MARGIN
        )
        raw_strong = (
            raw_score <= self.CURRENT_CHAR_RAW_STRONG_SCORE
            and raw_margin >= self.CURRENT_CHAR_RAW_STRONG_MARGIN
        )
        core_strong = (
            core_scores is not None
            and core_score <= self.CURRENT_CHAR_CORE_STRONG_SCORE
            and core_margin >= self.CURRENT_CHAR_CORE_STRONG_MARGIN
        )

        if core_scores is not None and raw_idx == core_idx and raw_candidate:
            index = raw_idx
            score = max(0.0, min(raw_score, core_score) - min(raw_margin, core_margin))
            accepted = True
            strong = True
            reason = "raw_core_agree"
        elif core_strong:
            raw_support = (
                raw_scores[core_idx] <= self.CURRENT_CHAR_RAW_CANDIDATE_SCORE
                or raw_scores[core_idx] <= raw_score + 0.20
            )
            if raw_support:
                index = core_idx
                score = max(0.0, core_score - core_margin)
                accepted = True
                strong = core_margin >= self.CURRENT_CHAR_RAW_CANDIDATE_MARGIN
                reason = "core_strong"
        elif raw_strong:
            index = raw_idx
            score = max(0.0, raw_score - min(raw_margin, self.CURRENT_CHAR_RAW_STRONG_MARGIN))
            accepted = True
            strong = True
            reason = "raw_strong"

        scores = self._build_current_char_scores(index, score, accepted)
        if 0 <= index < len(boxes):
            self.draw_boxes(boxes=boxes[index], color="red")

        return _CurrentCharDetection(
            index=index if accepted else -1,
            score=score if accepted else 1.0,
            scores=scores,
            accepted=accepted,
            strong=strong,
            reason=reason,
            raw_scores=raw_scores,
            core_scores=core_scores,
        )

    def _apply_current_char_tracker(self, detection):
        now = time.time()
        tracker = self._current_char_tracker
        if detection.accepted:
            tracker["index"] = detection.index
            tracker["score"] = detection.score
            tracker["time"] = now
            tracker["reason"] = detection.reason
            return detection

        if tracker["index"] != -1 and now - tracker["time"] <= self.CURRENT_CHAR_STICKY_SECONDS:
            index = tracker["index"]
            score = max(tracker["score"], self.CURRENT_CHAR_ACCEPT_SCORE)
            scores = self._build_current_char_scores(index, score, accepted=True)
            return _CurrentCharDetection(
                index=index,
                score=scores[index],
                scores=scores,
                accepted=True,
                strong=False,
                reason=f"sticky:{tracker['reason']}",
                raw_scores=detection.raw_scores,
                core_scores=detection.core_scores,
            )

        return detection

    def _get_current_char_detection(self, frame=None):
        detection = self._detect_current_char_once(frame=frame)
        if frame is None:
            return self._apply_current_char_tracker(detection)
        return detection

    def _get_char_match_scores(self, frame=None):
        """Return four slot scores; lower means the slot is the current char."""
        return self._get_current_char_detection(frame=frame).scores

    def is_char_at_index(self, index, threshold=0.5, frame=None):
        detection = self._get_current_char_detection(frame=frame)
        score = detection.scores[index]
        new = f"idx {index} conf {score:.3f} {detection.reason}"
        stable_target = (
            detection.reason in self.CURRENT_CHAR_STABLE_ACCEPT_REASONS
            and score <= self.CURRENT_CHAR_REJECT_SCORE
        )
        if detection.accepted and detection.index == index and (score < threshold or stable_target):
            self.info_set("current char", new)
            return True
        self.run_with_interval(lambda: self.info_set("current char", new), 0.5)

    def get_current_char_index(self):
        # frame = self.frame
        detection = self._get_current_char_detection()
        if detection.accepted:
            self.log_debug(
                f"current_char found at {detection.index} "
                f"with score {detection.score:.4f} ({detection.reason})"
            )
            # if detection.score > 0.5:
            #     self.screenshot("low_conf", frame)
            return detection.index

        self.log_debug(
            f"current_char rejected ({detection.reason}) raw={detection.raw_scores} "
            f"core={detection.core_scores}"
        )
        return -1

    def _multi_stage_char_match(self):
        results = [None, None, None, None]
        contrast_steps = [0, 30, 60, 90]

        for c_val in contrast_steps:
            if all(res is not None for res in results):
                break

            for i in range(4):
                if results[i] is not None:
                    continue

                def process(image, current_c=c_val):
                    return iu.adjust_lightness_contrast_lab(image, brightness=0, contrast=current_c)

                res = self.find_one(
                    f"char_{i + 1}_text",
                    threshold=0.7,
                    frame_processor=process,
                    mask_function=iu.mask_outside_white_rect,
                    horizontal_variance=0.005,
                )
                if res:
                    results[i] = res

        return results

    def _update_char_ui_offset(self):
        # now = time.time()
        arr = self._multi_stage_char_match()
        results = [
            c.x < self._get_char_text_box(idx).x for idx, c in enumerate(arr) if c is not None
        ]

        if results:
            self._char_ui_offset = sum(results) > (len(results) / 2)
        else:
            self._char_ui_offset = False
        # logger.debug(f"update_char_ui_offset cost {time.time() - now:.3f}")
        return arr
