"""[lw] Volleyball spike-cue detection and input isolation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from src.tasks.VolleyballTask import VolleyballTask

    _TaskProxy = VolleyballTask
else:

    class _TaskProxy:
        pass


@dataclass(frozen=True)
class VolleyballSpikeCueMetrics:
    active: bool
    color_ratio: float
    core_ratio: float
    component_area_ratio: float
    component_width_ratio: float
    component_height_ratio: float
    component_fill_ratio: float
    row_coverage: float
    column_coverage: float
    active_cell_count: int


SPIKE_CUE_COLOR = {
    "r": (71, 100),
    "g": (155, 175),
    "b": (167, 187),
}


def analyze_volleyball_spike_cue(image: np.ndarray | None) -> VolleyballSpikeCueMetrics:
    """Detect the pale-blue spike cue while rejecting thin court lines."""
    empty = VolleyballSpikeCueMetrics(
        False,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0,
    )
    if image is None or image.size == 0 or image.ndim != 3 or image.shape[2] < 3:
        return empty

    image = image[:, :, :3]
    mask = cv2.inRange(
        image,
        (
            SPIKE_CUE_COLOR["b"][0],
            SPIKE_CUE_COLOR["g"][0],
            SPIKE_CUE_COLOR["r"][0],
        ),
        (
            SPIKE_CUE_COLOR["b"][1],
            SPIKE_CUE_COLOR["g"][1],
            SPIKE_CUE_COLOR["r"][1],
        ),
    )
    height, width = mask.shape
    color_ratio = cv2.countNonZero(mask) / mask.size

    core = mask[
        int(height * 0.30) : int(height * 0.82),
        int(width * 0.30) : int(width * 0.78),
    ]
    core_ratio = cv2.countNonZero(core) / core.size if core.size else 0.0

    row_min_pixels = max(2, int(np.ceil(width * 0.04)))
    column_min_pixels = max(2, int(np.ceil(height * 0.06)))
    row_coverage = float(np.mean(np.count_nonzero(mask, axis=1) >= row_min_pixels))
    column_coverage = float(np.mean(np.count_nonzero(mask, axis=0) >= column_min_pixels))
    active_cell_count = 0
    for grid_y in range(3):
        for grid_x in range(3):
            cell = mask[
                grid_y * height // 3 : (grid_y + 1) * height // 3,
                grid_x * width // 3 : (grid_x + 1) * width // 3,
            ]
            if cell.size and cv2.countNonZero(cell) / cell.size >= 0.02:
                active_cell_count += 1

    component_area_ratio = 0.0
    component_width_ratio = 0.0
    component_height_ratio = 0.0
    component_fill_ratio = 0.0
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if component_count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        component_width = int(stats[largest, cv2.CC_STAT_WIDTH])
        component_height = int(stats[largest, cv2.CC_STAT_HEIGHT])
        component_area = int(stats[largest, cv2.CC_STAT_AREA])
        component_area_ratio = component_area / mask.size
        component_width_ratio = component_width / width
        component_height_ratio = component_height / height
        component_fill_ratio = component_area / (component_width * component_height)

    active = (
        color_ratio >= 0.06
        and core_ratio >= 0.04
        and row_coverage >= 0.20
        and column_coverage >= 0.20
        and active_cell_count >= 6
        and component_area_ratio >= 0.02
        and component_width_ratio >= 0.12
        and component_height_ratio >= 0.10
        and component_fill_ratio >= 0.12
    )
    return VolleyballSpikeCueMetrics(
        active,
        color_ratio,
        core_ratio,
        component_area_ratio,
        component_width_ratio,
        component_height_ratio,
        component_fill_ratio,
        row_coverage,
        column_coverage,
        active_cell_count,
    )


class VolleyballSpikeExtMixin(_TaskProxy):
    """Provide the LW spike state without duplicating the RU match loop."""

    LW_SPIKE_CANDIDATE = "candidate"
    LW_SPIKE_CONFIRMED = "confirmed"
    LW_SPIKE_RECOVERY = "recovery"

    SPIKE_CUE_ROI = (0.8562, 0.8500, 0.9137, 0.9243)
    SPIKE_JUMP_ACTION_ROI = (0.975, 0.717, 0.993, 0.743)
    SPIKE_JUMP_ACTION_WHITE_THRESHOLD = 0.04
    SPIKE_CUE_CONFIRM_FRAMES = 2
    SPIKE_CLEAR_CONFIRM_SECONDS = 0.08
    SPIKE_CLEAR_TIMEOUT_SECONDS = 1.0
    SPIKE_DELAY_AFTER_CLEAR_SECONDS = 0.6
    SPIKE_POST_K_LOCK_SECONDS = 0.35
    SPIKE_RECOVERY_RALLY_FRAMES = 2
    SPIKE_RECOVERY_TIMEOUT_SECONDS = 1.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lw_reset_spike_state()

    def lw_is_spike_cue(self) -> bool:
        box = self.box_of_screen(*self.SPIKE_CUE_ROI, name="volleyball_spike_cue")
        frame = getattr(self, "frame", None)
        if frame is None or frame.size == 0:
            self._lw_spike_cue_metrics = analyze_volleyball_spike_cue(None)
            return False
        if (
            box.x < 0
            or box.y < 0
            or box.x + box.width > frame.shape[1]
            or box.y + box.height > frame.shape[0]
        ):
            self._lw_spike_cue_metrics = analyze_volleyball_spike_cue(None)
            return False

        crop = frame[box.y : box.y + box.height, box.x : box.x + box.width]
        metrics = analyze_volleyball_spike_cue(crop)
        self._lw_spike_cue_metrics = metrics
        box.confidence = metrics.color_ratio
        self.draw_boxes(box.name, box)
        return metrics.active

    def lw_is_spike_jump_action_active(self) -> bool:
        from src import text_white_color

        box = self.box_of_screen(
            *self.SPIKE_JUMP_ACTION_ROI,
            name="volleyball_spike_jump_action",
        )
        return (
            self.calculate_color_percentage(text_white_color, box)
            > self.SPIKE_JUMP_ACTION_WHITE_THRESHOLD
        )

    def lw_observe_spike_phase(self, rally_active: bool, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        if self._lw_spike_recovery_active:
            return self.lw_observe_spike_recovery(rally_active, now)
        if self._spike_phase_active:
            return self.LW_SPIKE_CONFIRMED
        if not rally_active:
            self._lw_spike_candidate_frames = 0
            return None

        if not self.lw_is_spike_cue():
            if self._lw_spike_candidate_frames:
                self.log_info("spike cue candidate cleared before confirmation")
            self._lw_spike_candidate_frames = 0
            return None

        self._lw_spike_candidate_frames += 1
        metrics = self._lw_spike_cue_metrics
        if self._lw_spike_candidate_frames < self.SPIKE_CUE_CONFIRM_FRAMES:
            self.log_info(
                "spike cue candidate; "
                f"{self._lw_spike_candidate_frames}/{self.SPIKE_CUE_CONFIRM_FRAMES} frames, "
                f"color={metrics.color_ratio:.3f}, core={metrics.core_ratio:.3f}"
            )
            return self.LW_SPIKE_CANDIDATE

        self.log_info(
            "spike cue confirmed; "
            f"{self._lw_spike_candidate_frames} consecutive frames, "
            f"color={metrics.color_ratio:.3f}, core={metrics.core_ratio:.3f}"
        )
        return self.LW_SPIKE_CONFIRMED

    def lw_wait_for_stable_spike_clear(self) -> tuple[bool, float | None]:
        clear_started_at = None

        def stable_clear():
            nonlocal clear_started_at
            if self.lw_is_spike_cue():
                clear_started_at = None
                return False
            now = time.monotonic()
            if clear_started_at is None:
                clear_started_at = now
                return False
            return now - clear_started_at >= self.SPIKE_CLEAR_CONFIRM_SECONDS

        confirmed = bool(
            self.wait_until(stable_clear, time_out=self.SPIKE_CLEAR_TIMEOUT_SECONDS)
        )
        return confirmed, clear_started_at if confirmed else None

    def lw_handle_spike_cue(self):
        if self._spike_phase_active:
            return
        self._spike_phase_active = True
        self._lw_spike_candidate_frames = 0
        started_at = time.monotonic()
        self.log_info("spike cue lock entered after consecutive confirmation")

        cue_cleared, first_clear_at = self.lw_wait_for_stable_spike_clear()
        observed_at = time.monotonic()
        if cue_cleared and first_clear_at is not None:
            clear_wait = first_clear_at - started_at
            confirm_wait = observed_at - first_clear_at
            self.log_info(
                "spike cue stable clear; "
                f"first clear after {clear_wait:.3f}s, confirmed in {confirm_wait:.3f}s"
            )
            k_due_at = first_clear_at + self.SPIKE_DELAY_AFTER_CLEAR_SECONDS
        else:
            self.log_warning(
                "spike cue clear timed out; using timeout as the K timing anchor"
            )
            k_due_at = observed_at + self.SPIKE_DELAY_AFTER_CLEAR_SECONDS

        remaining = max(0.0, k_due_at - time.monotonic())
        if remaining:
            self.sleep(remaining)
        sent = self.send_key("k")
        self._lw_spike_k_sent_at = time.monotonic()
        self._lw_spike_recovery_active = True
        self._lw_spike_recovery_rally_frames = 0
        total_elapsed = self._lw_spike_k_sent_at - started_at
        if sent:
            self.log_info(f"volleyball input: spike K; {total_elapsed:.3f}s after spike lock")
        else:
            self.log_warning("volleyball input rejected: spike K")

    def lw_observe_spike_recovery(self, rally_active: bool, now: float) -> str | None:
        elapsed = now - self._lw_spike_k_sent_at
        if elapsed >= self.SPIKE_RECOVERY_TIMEOUT_SECONDS:
            self.log_warning(
                f"spike recovery timed out after {elapsed:.3f}s; resuming recognition"
            )
            self.lw_reset_spike_state()
            return None

        if elapsed < self.SPIKE_POST_K_LOCK_SECONDS:
            self._lw_spike_recovery_rally_frames = 0
            return self.LW_SPIKE_RECOVERY

        if self.lw_is_spike_jump_action_active() or not rally_active:
            self._lw_spike_recovery_rally_frames = 0
            return self.LW_SPIKE_RECOVERY

        self._lw_spike_recovery_rally_frames += 1
        if self._lw_spike_recovery_rally_frames < self.SPIKE_RECOVERY_RALLY_FRAMES:
            return self.LW_SPIKE_RECOVERY

        self.log_info(
            "spike recovery released; "
            f"{self._lw_spike_recovery_rally_frames} consecutive rally frames after "
            f"{elapsed:.3f}s"
        )
        self.lw_reset_spike_state()
        return None

    def lw_reset_spike_state(self):
        self._spike_phase_active = False
        self._lw_spike_candidate_frames = 0
        self._lw_spike_recovery_active = False
        self._lw_spike_recovery_rally_frames = 0
        self._lw_spike_k_sent_at = 0.0
        self._lw_spike_cue_metrics = analyze_volleyball_spike_cue(None)
