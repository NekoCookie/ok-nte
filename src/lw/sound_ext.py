# [lw] 声音触发的用户扩展: 完美闪避确认、闪避时刻查询、待执行动作查询、闪避暂停开关。
# 接线: SoundListener 发布每帧分数; SoundCombatContext 负责确认窗口和角色结果回调。

import threading
import time
import wave
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from ok import Logger, get_path_relative_to_exe

from src.sound_trigger.capture.base import CAPTURE_SAMPLE_RATE


logger = Logger.get_logger(__name__)


@dataclass
class _DodgeConfirmation:
    task: object
    started_at: float = field(default_factory=time.perf_counter)
    dodge_started_at: float | None = None
    confirmed_at: float | None = None
    event: threading.Event = field(default_factory=threading.Event)
    confirmed: bool = False
    cancelled: bool = False
    peak_counter_score: float = 0.0
    score_observations: list[tuple[float, float]] = field(default_factory=list)
    confirmation_candidates: list[float] = field(default_factory=list)
    audio_sample_name: str = ""


@dataclass
class _AudioDiagnosticCapture:
    sample_name: str
    started_at: float
    ends_at: float


@dataclass(frozen=True)
class SoundDodgeOutcome:
    perfect_dodge: bool
    result: str
    anchor_monotonic: float


class SoundListenerExtMixin:
    """Publish raw match scores before RU trigger debounce or action arbitration."""

    AUDIO_DIAGNOSTIC_CAPTURE = False
    AUDIO_DIAGNOSTIC_SECONDS = 1.0
    AUDIO_HISTORY_SECONDS = 1.5
    AUDIO_SAMPLE_LIMIT = 40

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_scores_updated = None
        self._lw_audio_lock = threading.Lock()
        self._lw_audio_history = deque()
        self._lw_audio_history_samples = 0
        self._lw_audio_total_samples = 0
        self._lw_audio_captures = []
        self._lw_audio_sequence = 0

    def lw_publish_scores(self, dodge_score: float, counter_score: float) -> None:
        callback = self.on_scores_updated
        if callback is not None:
            callback(dodge_score, counter_score)

    def lw_publish_audio_chunk(self, chunk: np.ndarray, ended_at: float | None = None) -> None:
        """Keep a short rolling buffer and finish requested post-dodge WAV samples."""

        if chunk is None or len(chunk) == 0:
            return
        ended_at = time.perf_counter() if ended_at is None else ended_at
        chunk = np.ascontiguousarray(chunk, dtype=np.float32)
        started_at = ended_at - len(chunk) / CAPTURE_SAMPLE_RATE
        completed = []
        with self._lw_audio_lock:
            self._lw_audio_history.append((started_at, ended_at, chunk.copy()))
            self._lw_audio_history_samples += len(chunk)
            self._lw_audio_total_samples += len(chunk)
            history_samples = round(self.AUDIO_HISTORY_SECONDS * CAPTURE_SAMPLE_RATE)
            while (
                self._lw_audio_history
                and self._lw_audio_history_samples - len(self._lw_audio_history[0][2])
                >= history_samples
            ):
                _, _, discarded = self._lw_audio_history.popleft()
                self._lw_audio_history_samples -= len(discarded)
            pending = []
            for capture in self._lw_audio_captures:
                if ended_at < capture.ends_at:
                    pending.append(capture)
                    continue
                audio = self._lw_extract_audio_window(capture.started_at, capture.ends_at)
                completed.append((capture.sample_name, audio))
            self._lw_audio_captures = pending
        for sample_name, audio in completed:
            self._lw_write_audio_async(sample_name, audio)

    def lw_audio_sample_position(self) -> int:
        with self._lw_audio_lock:
            return self._lw_audio_total_samples

    def lw_latest_audio_window(self, sample_count: int) -> np.ndarray | None:
        """Return the newest continuous producer-side samples without queue gaps."""

        if sample_count <= 0:
            return np.empty(0, dtype=np.float32)
        with self._lw_audio_lock:
            if self._lw_audio_history_samples < sample_count:
                return None
            remaining = sample_count
            parts = []
            for _, _, chunk in reversed(self._lw_audio_history):
                if remaining <= 0:
                    break
                take = min(remaining, len(chunk))
                parts.append(chunk[-take:])
                remaining -= take
        return np.concatenate(parts[::-1])

    def lw_request_dodge_audio_capture(self, started_at: float) -> str:
        """Capture one second from the dodge-input timestamp using the rolling buffer."""

        if not self.AUDIO_DIAGNOSTIC_CAPTURE:
            return ""
        with self._lw_audio_lock:
            self._lw_audio_sequence += 1
            stamp = time.strftime("%Y%m%d_%H%M%S")
            sample_name = f"dodge_{stamp}_{self._lw_audio_sequence:04d}.wav"
            self._lw_audio_captures.append(
                _AudioDiagnosticCapture(
                    sample_name=sample_name,
                    started_at=started_at,
                    ends_at=started_at + self.AUDIO_DIAGNOSTIC_SECONDS,
                )
            )
        return sample_name

    def _lw_extract_audio_window(self, started_at: float, ends_at: float) -> np.ndarray:
        sample_count = max(0, round((ends_at - started_at) * CAPTURE_SAMPLE_RATE))
        if sample_count == 0:
            return np.empty(0, dtype=np.float32)

        parts = []
        found_start = False
        for chunk_start, chunk_end, chunk in self._lw_audio_history:
            if not found_start:
                if started_at > chunk_end:
                    continue
                source_start = round((started_at - chunk_start) * CAPTURE_SAMPLE_RATE)
                source_start = max(0, min(len(chunk), source_start))
                chunk = chunk[source_start:]
                found_start = True
            if len(chunk) > 0:
                parts.append(chunk)

        audio = np.concatenate(parts) if parts else np.empty(0, dtype=np.float32)
        if len(audio) >= sample_count:
            return np.ascontiguousarray(audio[:sample_count], dtype=np.float32)
        return np.pad(audio, (0, sample_count - len(audio))).astype(np.float32, copy=False)

    def _lw_write_audio_async(self, sample_name: str, audio: np.ndarray) -> None:
        def write_sample():
            try:
                folder = Path(get_path_relative_to_exe("logs", "sound_dodge_samples"))
                folder.mkdir(parents=True, exist_ok=True)
                pcm = np.clip(audio, -1.0, 1.0)
                pcm = np.asarray(pcm * 32767, dtype="<i2")
                with wave.open(str(folder / sample_name), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(CAPTURE_SAMPLE_RATE)
                    output.writeframes(pcm.tobytes())
                self._lw_prune_audio_samples(folder)
                logger.info(
                    f"Saved dodge audio sample: {sample_name}, "
                    f"duration={len(audio) / CAPTURE_SAMPLE_RATE:.3f}s"
                )
            except Exception as exc:
                logger.error(f"Failed to save dodge audio sample {sample_name}: {exc}")

        threading.Thread(target=write_sample, daemon=True, name="DodgeAudioSampleWriter").start()

    def _lw_prune_audio_samples(self, folder: Path) -> None:
        samples = sorted(
            folder.glob("dodge_*.wav"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_sample in samples[self.AUDIO_SAMPLE_LIMIT :]:
            old_sample.unlink(missing_ok=True)


class SoundContextExtMixin:
    _dodge_paused = False
    DEFAULT_ORDINARY_DODGE_WAIT = 0.5
    MAX_ORDINARY_DODGE_WAIT = 5.0
    COUNTER_SOUND_QUIET_FRAMES = 2
    DODGE_RESULT_MANUAL_PERFECT = "手动完美"
    DODGE_RESULT_ORDINARY = "普通闪避"
    DODGE_RESULT_AUTO_PERFECT = "自动完美"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lw_ordinary_dodge_wait = self.DEFAULT_ORDINARY_DODGE_WAIT
        self._lw_dodge_confirmation = None
        self._lw_counter_sound_active = False
        self._lw_counter_sound_consumed = False
        self._lw_counter_sound_quiet_frames = 0
        self._lw_manual_perfect_dodge_time = 0.0
        self._lw_pending_manual_perfect_wall = 0.0
        self._lw_pending_manual_perfect_monotonic = 0.0
        self._lw_last_dodge_outcome = None

    def lw_update_ordinary_dodge_wait(self, value) -> None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = self.DEFAULT_ORDINARY_DODGE_WAIT
        self._lw_ordinary_dodge_wait = max(0.0, min(self.MAX_ORDINARY_DODGE_WAIT, value))

    def lw_ordinary_dodge_wait_for_task(self, task) -> float:
        """Read the ordinary-dodge wait selected for the current character."""

        default_wait = self._lw_ordinary_dodge_wait
        try:
            from src.lw.requiem_zankou_axis import REQUIEM_IMPL_ID
            from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

            config_task = task.get_task_by_class(RequiemCombatConfigTask)
            config = config_task.config
            config_key = RequiemCombatConfigTask.CONF_ORDINARY_DODGE_WAIT
            fallback_wait = default_wait
            get_current_char = getattr(task, "get_current_char", None)
            current_char = (
                get_current_char(raise_exception=False) if callable(get_current_char) else None
            )
            if getattr(current_char, "impl_id", "") == REQUIEM_IMPL_ID:
                config_key = RequiemCombatConfigTask.CONF_REQUIEM_ORDINARY_DODGE_WAIT
                fallback_wait = self.DEFAULT_ORDINARY_DODGE_WAIT
            value = float(
                config.get(
                    config_key,
                    fallback_wait,
                )
            )
            return max(0.0, min(self.MAX_ORDINARY_DODGE_WAIT, value))
        except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
            return default_wait

    def lw_bind_score_listener(self, listener) -> None:
        listener.on_scores_updated = self.lw_observe_sound_scores

    def _lw_begin_dodge_confirmation(self, task) -> _DodgeConfirmation:
        with self._context_lock:
            previous = self._lw_dodge_confirmation
            if previous is not None:
                previous.cancelled = True
                previous.event.set()
            attempt = _DodgeConfirmation(task=task)
            self._lw_dodge_confirmation = attempt
            return attempt

    def lw_observe_sound_scores(self, _dodge_score: float, counter_score: float) -> None:
        """Confirm automatic dodges or queue one follow-up for a manual perfect dodge."""

        try:
            counter_score = float(counter_score)
        except (TypeError, ValueError):
            return
        observed_at = time.perf_counter()
        queue_manual_perfect = False
        with self._context_lock:
            listener = self._listener
            threshold = getattr(listener, "counter_attack_threshold", 1.0)
            matched = counter_score > 0 and counter_score > threshold
            self._lw_update_counter_sound_event_locked(matched)

            attempt = self._lw_dodge_confirmation
            if attempt is not None and not attempt.cancelled:
                attempt.score_observations.append((observed_at, counter_score))
                if attempt.dodge_started_at is None or observed_at >= attempt.dodge_started_at:
                    attempt.peak_counter_score = max(attempt.peak_counter_score, counter_score)
                if matched and not attempt.confirmed:
                    attempt.confirmation_candidates.append(observed_at)
                    attempt.confirmed_at = min(attempt.confirmation_candidates)
                    attempt.event.set()
                    self._lw_counter_sound_consumed = True
            elif matched and not self._lw_counter_sound_consumed:
                self._lw_counter_sound_consumed = True
                self._lw_pending_manual_perfect_wall = time.time()
                self._lw_pending_manual_perfect_monotonic = time.monotonic()
                queue_manual_perfect = True

        if queue_manual_perfect:
            queue_action = getattr(self, "_queue_action", None)
            if callable(queue_action):
                queue_action("manual_perfect")

    def _lw_update_counter_sound_event_locked(self, matched: bool) -> None:
        if matched:
            if not self._lw_counter_sound_active:
                self._lw_counter_sound_active = True
                self._lw_counter_sound_consumed = False
            self._lw_counter_sound_quiet_frames = 0
            return
        if not self._lw_counter_sound_active:
            return
        self._lw_counter_sound_quiet_frames += 1
        if self._lw_counter_sound_quiet_frames < self.COUNTER_SOUND_QUIET_FRAMES:
            return
        self._lw_counter_sound_active = False
        self._lw_counter_sound_consumed = False
        self._lw_counter_sound_quiet_frames = 0

    def lw_reset_counter_sound_event(self) -> None:
        with self._context_lock:
            self._lw_counter_sound_active = False
            self._lw_counter_sound_consumed = False
            self._lw_counter_sound_quiet_frames = 0
            self._lw_pending_manual_perfect_wall = 0.0
            self._lw_pending_manual_perfect_monotonic = 0.0
            self._lw_last_dodge_outcome = None

    def lw_counter_trigger_action(self) -> str | None:
        """Return the sole action for a counter callback, suppressing an already-seen sound."""

        with self._context_lock:
            if self._lw_counter_sound_active and self._lw_counter_sound_consumed:
                return None
            if not self._lw_counter_sound_active:
                self._lw_counter_sound_active = True
                self._lw_counter_sound_quiet_frames = 0
            attempt = self._lw_dodge_confirmation
            if attempt is not None and not attempt.cancelled:
                self._lw_counter_sound_consumed = True
                if attempt.confirmed:
                    return None
                observed_at = time.perf_counter()
                attempt.confirmation_candidates.append(observed_at)
                attempt.confirmed_at = min(attempt.confirmation_candidates)
                attempt.event.set()
                return None
            self._lw_counter_sound_consumed = True
            self._lw_pending_manual_perfect_wall = time.time()
            self._lw_pending_manual_perfect_monotonic = time.monotonic()
            return "manual_perfect"

    def _lw_monotonic_from_perf_counter(self, observed_at: float) -> float:
        return time.monotonic() - max(0.0, time.perf_counter() - observed_at)

    def _lw_record_dodge_outcome(
        self,
        *,
        perfect_dodge: bool,
        result: str,
        anchor_monotonic: float,
    ) -> None:
        with self._context_lock:
            self._lw_last_dodge_outcome = SoundDodgeOutcome(
                perfect_dodge=perfect_dodge,
                result=result,
                anchor_monotonic=anchor_monotonic,
            )

    @staticmethod
    def _lw_prepare_current_char_for_sound_dodge(task) -> None:
        prepare = getattr(task, "prepare_current_char_for_sound_dodge", None)
        if not callable(prepare):
            return
        try:
            prepare()
        except Exception as exc:
            logger.error(f"Character sound-dodge preparation failed: {exc}")

    def lw_resolve_manual_perfect_dodge(self, task=None) -> bool:
        self._lw_prepare_current_char_for_sound_dodge(task)
        with self._context_lock:
            anchor_monotonic = self._lw_pending_manual_perfect_monotonic
            manual_wall = self._lw_pending_manual_perfect_wall
            self._lw_pending_manual_perfect_monotonic = 0.0
            self._lw_pending_manual_perfect_wall = 0.0
        if anchor_monotonic <= 0:
            anchor_monotonic = time.monotonic()
        if manual_wall <= 0:
            manual_wall = time.time()
        self._lw_manual_perfect_dodge_time = manual_wall
        self._lw_record_dodge_outcome(
            perfect_dodge=True,
            result=self.DODGE_RESULT_MANUAL_PERFECT,
            anchor_monotonic=anchor_monotonic,
        )
        logger.info(f"声音闪避结果: {self.DODGE_RESULT_MANUAL_PERFECT}")
        return True

    def lw_execute_dodge_with_confirmation(self, trigger, task) -> bool | None:
        """Execute dodge, then return True for perfect, False for timeout, or None if cancelled."""

        attempt = self._lw_begin_dodge_confirmation(task)
        try:
            previous_dodge_at = getattr(trigger, "last_dodge_time", 0.0)
            trigger.execute_dodge()
            dodge_at = getattr(trigger, "last_dodge_time", 0.0)
            if dodge_at <= previous_dodge_at:
                self.lw_cancel_dodge_confirmation("dodge input was not executed", attempt)
                return None
            dodge_started_at = getattr(trigger, "last_dodge_monotonic", attempt.started_at)
            ignored_before_shift = None
            with self._context_lock:
                if self._lw_dodge_confirmation is not attempt or attempt.cancelled:
                    return None
                attempt.dodge_started_at = dodge_started_at
                attempt.peak_counter_score = max(
                    (
                        score
                        for observed_at, score in attempt.score_observations
                        if observed_at >= dodge_started_at
                    ),
                    default=0.0,
                )
                attempt.confirmed_at = min(
                    (
                        observed_at
                        for observed_at in attempt.confirmation_candidates
                        if observed_at >= dodge_started_at
                    ),
                    default=None,
                )
                ignored_before_shift = max(
                    (
                        observed_at
                        for observed_at in attempt.confirmation_candidates
                        if observed_at < dodge_started_at
                    ),
                    default=None,
                )
            listener = self._listener
            if listener is not None:
                attempt.audio_sample_name = listener.lw_request_dodge_audio_capture(
                    dodge_started_at
                )
            ordinary_dodge_wait = self.lw_ordinary_dodge_wait_for_task(task)
            deadline = dodge_started_at + ordinary_dodge_wait
            while True:
                with self._context_lock:
                    if self._lw_dodge_confirmation is not attempt or attempt.cancelled:
                        return None
                    confirmed_at = attempt.confirmed_at
                    if confirmed_at is not None and confirmed_at < dodge_started_at:
                        ignored_before_shift = confirmed_at
                        attempt.confirmed_at = min(
                            (
                                observed_at
                                for observed_at in attempt.confirmation_candidates
                                if observed_at >= dodge_started_at
                            ),
                            default=None,
                        )
                        attempt.event.clear()
                        confirmed_at = attempt.confirmed_at
                    now = time.perf_counter()
                    if confirmed_at is not None and confirmed_at <= deadline:
                        attempt.confirmed = True
                        self._lw_dodge_confirmation = None
                        break
                    if now >= deadline:
                        attempt.confirmed_at = None
                        self._lw_dodge_confirmation = None
                        break
                    attempt.event.clear()
                    remaining = deadline - now
                attempt.event.wait(remaining)
            confirmed = attempt.confirmed
            confirmed_at = attempt.confirmed_at
            peak = attempt.peak_counter_score
        except Exception:
            self.lw_cancel_dodge_confirmation("dodge confirmation raised", attempt)
            raise

        if ignored_before_shift is not None:
            logger.info(
                "Ignored perfect dodge sound before Shift: "
                f"before_shift={dodge_started_at - ignored_before_shift:.3f}s"
            )
        if confirmed:
            after_shift = confirmed_at - dodge_started_at
            self._lw_record_dodge_outcome(
                perfect_dodge=True,
                result=self.DODGE_RESULT_AUTO_PERFECT,
                anchor_monotonic=self._lw_monotonic_from_perf_counter(confirmed_at),
            )
            logger.info(
                f"声音闪避结果: {self.DODGE_RESULT_AUTO_PERFECT}; "
                f"peak counter_score={peak:.4f}; "
                f"after_shift={after_shift:.3f}s; "
                f"sample={attempt.audio_sample_name or 'none'}"
            )
            return True
        self._lw_record_dodge_outcome(
            perfect_dodge=False,
            result=self.DODGE_RESULT_ORDINARY,
            anchor_monotonic=self._lw_monotonic_from_perf_counter(dodge_started_at),
        )
        logger.info(
            f"声音闪避结果: {self.DODGE_RESULT_ORDINARY}; "
            f"waited={ordinary_dodge_wait:.2f}s after Shift; "
            f"peak counter_score={peak:.4f}; "
            f"sample={attempt.audio_sample_name or 'none'}; resuming normal combat"
        )
        return False

    def lw_cancel_dodge_confirmation(self, reason: str, expected=None) -> bool:
        with self._context_lock:
            attempt = self._lw_dodge_confirmation
            if attempt is None or (expected is not None and attempt is not expected):
                return False
            self._lw_dodge_confirmation = None
            attempt.cancelled = True
            attempt.event.set()
        logger.info(f"Dodge confirmation cancelled: {reason}")
        return True

    def lw_dispatch_dodge_outcome(
        self,
        task,
        perfect_dodge: bool,
        dodge_result: str,
    ) -> None:
        with self._context_lock:
            current_task = self._trigger.task if self._trigger else self._pending_task
        if current_task is not task:
            return
        callback = getattr(task, "after_sound_dodge_resolved", None)
        if callback is None:
            return
        try:
            callback(perfect_dodge=perfect_dodge, dodge_result=dodge_result)
        except Exception as exc:
            logger.error(f"Sound dodge outcome callback failed: {exc}")

    def last_dodge_time(self):
        """上次声音触发闪避的时刻(time.time()), 没触发过返回 0。
        闪避是我方主动触发(记了时刻), 所以"放完技能是否立刻闪避"可确定性判断, 不必靠图标猜。"""
        trigger = self._trigger
        automatic_dodge_at = getattr(trigger, "last_dodge_time", 0.0) if trigger else 0.0
        return max(automatic_dodge_at, self._lw_manual_perfect_dodge_time)

    def last_dodge_outcome(self) -> SoundDodgeOutcome | None:
        with self._context_lock:
            return self._lw_last_dodge_outcome

    def has_pending_action(self):
        """是否有"新的声音闪避在排队待执行"。用于闪避反击(双4a)期间: 反击本身在处理"当前这次"
        闪避、combat_interrupt 尚为当前闪避而 set(不能拿它判断中止), 但一旦来了**新的**敌人攻击
        会入队 _pending_action —— 反击应立刻中止让位, 把主线程交回去执行那次救命闪避。"""
        with self._context_lock:
            return self._pending_action is not None

    @classmethod
    def set_dodge_paused(cls, paused):
        """暂停/恢复声音自动闪避。仅用于"安魂曲配置"的闪避反击测试: 跑一整轮期间暂停, 免得
        SoundTriggerTask 对真·敌人攻击的自动闪避插进测试的 combo 里、看不清完整一轮。实战不用。"""
        cls._dodge_paused = bool(paused)
