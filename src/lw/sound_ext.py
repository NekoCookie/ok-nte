# [lw] 声音触发的用户扩展: 完美闪避确认、闪避时刻查询、待执行动作查询、闪避暂停开关。
# 接线: SoundListener 发布每帧分数; SoundCombatContext 负责确认窗口和角色结果回调。

import threading
import time
from dataclasses import dataclass, field

from ok import Logger


logger = Logger.get_logger(__name__)


@dataclass
class _DodgeConfirmation:
    task: object
    started_at: float = field(default_factory=time.monotonic)
    event: threading.Event = field(default_factory=threading.Event)
    confirmed: bool = False
    cancelled: bool = False
    peak_counter_score: float = 0.0


class SoundListenerExtMixin:
    """Publish raw match scores before RU trigger debounce or action arbitration."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_scores_updated = None

    def lw_publish_scores(self, dodge_score: float, counter_score: float) -> None:
        callback = self.on_scores_updated
        if callback is not None:
            callback(dodge_score, counter_score)


class SoundContextExtMixin:
    _dodge_paused = False
    DEFAULT_PERFECT_DODGE_WAIT = 0.5
    MAX_PERFECT_DODGE_WAIT = 5.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lw_perfect_dodge_wait = self.DEFAULT_PERFECT_DODGE_WAIT
        self._lw_dodge_confirmation = None

    def lw_update_perfect_dodge_wait(self, value) -> None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = self.DEFAULT_PERFECT_DODGE_WAIT
        self._lw_perfect_dodge_wait = max(0.0, min(self.MAX_PERFECT_DODGE_WAIT, value))

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
        """Record a perfect-dodge sound even while the dodge action owns combat priority."""

        if self._lw_dodge_confirmation is None:
            return
        try:
            counter_score = float(counter_score)
        except (TypeError, ValueError):
            return
        with self._context_lock:
            attempt = self._lw_dodge_confirmation
            if attempt is None or attempt.cancelled:
                return
            attempt.peak_counter_score = max(attempt.peak_counter_score, counter_score)
            listener = self._listener
            threshold = getattr(listener, "counter_attack_threshold", 1.0)
            if counter_score <= 0 or counter_score <= threshold or attempt.confirmed:
                return
            attempt.confirmed = True
            attempt.event.set()
            elapsed = time.monotonic() - attempt.started_at
        logger.info(
            "Perfect dodge sound confirmed: "
            f"counter_score={counter_score:.4f}, threshold={threshold}, after={elapsed:.3f}s"
        )

    def lw_confirm_perfect_dodge_trigger(self) -> bool:
        """Consume RU's counter callback as confirmation when a dodge is awaiting its outcome."""

        with self._context_lock:
            attempt = self._lw_dodge_confirmation
            if attempt is None or attempt.cancelled:
                return False
            if not attempt.confirmed:
                attempt.confirmed = True
                attempt.event.set()
                elapsed = time.monotonic() - attempt.started_at
                logger.info(f"Perfect dodge counter trigger confirmed after {elapsed:.3f}s")
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
            if self._lw_perfect_dodge_wait > 0 and not attempt.confirmed:
                elapsed_since_dodge = time.monotonic() - attempt.started_at
                remaining = self._lw_perfect_dodge_wait - elapsed_since_dodge
                if remaining > 0:
                    attempt.event.wait(remaining)
            with self._context_lock:
                if self._lw_dodge_confirmation is not attempt or attempt.cancelled:
                    return None
                self._lw_dodge_confirmation = None
                confirmed = attempt.confirmed
                peak = attempt.peak_counter_score
        except Exception:
            self.lw_cancel_dodge_confirmation("dodge confirmation raised", attempt)
            raise

        if confirmed:
            return True
        logger.info(
            "No perfect dodge sound within "
            f"{self._lw_perfect_dodge_wait:.2f}s; peak counter_score={peak:.4f}; "
            "resuming normal combat"
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

    def lw_dispatch_dodge_outcome(self, task, perfect_dodge: bool) -> None:
        with self._context_lock:
            current_task = self._trigger.task if self._trigger else self._pending_task
        if current_task is not task:
            return
        callback = getattr(task, "after_sound_dodge_resolved", None)
        if callback is None:
            return
        try:
            callback(perfect_dodge=perfect_dodge)
        except Exception as exc:
            logger.error(f"Sound dodge outcome callback failed: {exc}")

    def last_dodge_time(self):
        """上次声音触发闪避的时刻(time.time()), 没触发过返回 0。
        闪避是我方主动触发(记了时刻), 所以"放完技能是否立刻闪避"可确定性判断, 不必靠图标猜。"""
        trigger = self._trigger
        return getattr(trigger, "last_dodge_time", 0.0) if trigger else 0.0

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
