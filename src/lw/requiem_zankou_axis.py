"""[lw] Requiem and Zankou coordinated-axis testing and combat integration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar
    from src.combat.planner import CombatContext


REQUIEM_IMPL_ID = "builtin:requiem"
ZANKOU_MAIN_DPS_IMPL_ID = "builtin:zankou_main_dps"
MIN_ATTACK_INTERVAL = 0.02


@dataclass(frozen=True, slots=True)
class CoordinatedAxisSettings:
    trigger_key: str = "8"
    requiem_switch_key: str = "1"
    zankou_switch_key: str = "2"
    requiem_attack_interval: float = 0.2
    requiem_attack_duration: float = 2.0
    zankou_switch_delay: float = 0.5
    zankou_hold_duration: float = 2.0
    zankou_normal_attack_duration: float = 2.0
    zankou_dodge_normal_attack_duration: float = 0.5


def _config_task(char: "BaseChar"):
    task = getattr(char, "task", None)
    get_task_by_class = getattr(task, "get_task_by_class", None)
    if not callable(get_task_by_class):
        return None

    from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

    try:
        return get_task_by_class(RequiemCombatConfigTask)
    except (LookupError, RuntimeError, TypeError):
        return None


def _team_chars(char: "BaseChar", context: "CombatContext | None") -> list["BaseChar"]:
    chars = getattr(context, "chars", None)
    if not isinstance(chars, (list, tuple)):
        chars = getattr(getattr(char, "task", None), "chars", None)
    if not isinstance(chars, (list, tuple)):
        return []
    return [teammate for teammate in chars if teammate is not None]


def coordinated_axis_partner(
    char: "BaseChar",
    context: "CombatContext | None",
    *,
    self_impl_id: str,
    partner_impl_id: str,
) -> "BaseChar | None":
    """Return the paired template only when automatic combat axis is enabled."""

    if str(getattr(char, "impl_id", "")) != self_impl_id:
        return None
    config_task = _config_task(char)
    config = getattr(config_task, "config", None)
    if not hasattr(config, "get"):
        return None
    enable_key = getattr(config_task, "CONF_COAXIS_COMBAT_ENABLE", "")
    if not enable_key or not bool(config.get(enable_key, False)):
        return None
    return next(
        (
            teammate
            for teammate in _team_chars(char, context)
            if teammate is not char
            and not bool(getattr(teammate, "is_dead", False))
            and str(getattr(teammate, "impl_id", "")) == partner_impl_id
        ),
        None,
    )


def _config_number(config_task, key: str, default: float) -> float:
    config = getattr(config_task, "config", None)
    if not hasattr(config, "get"):
        return default
    try:
        return max(0.0, float(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def coordinated_axis_settings(char: "BaseChar") -> CoordinatedAxisSettings:
    """Read the shared test/combat timings from Requiem configuration."""

    config_task = _config_task(char)
    if config_task is None:
        return CoordinatedAxisSettings()
    return CoordinatedAxisSettings(
        requiem_attack_interval=max(
            MIN_ATTACK_INTERVAL,
            _config_number(
                config_task,
                config_task.CONF_COAXIS_REQUIEM_INTERVAL,
                0.2,
            ),
        ),
        requiem_attack_duration=_config_number(
            config_task,
            config_task.CONF_COAXIS_REQUIEM_DURATION,
            2.0,
        ),
        zankou_switch_delay=_config_number(
            config_task,
            config_task.CONF_COAXIS_ZANKOU_SWITCH_DELAY,
            0.5,
        ),
        zankou_hold_duration=_config_number(
            config_task,
            config_task.CONF_COAXIS_ZANKOU_HOLD_DURATION,
            2.0,
        ),
        zankou_normal_attack_duration=_config_number(
            config_task,
            config_task.CONF_COAXIS_ZANKOU_NORMAL_DURATION,
            2.0,
        ),
        zankou_dodge_normal_attack_duration=_config_number(
            config_task,
            getattr(config_task, "CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION", ""),
            0.5,
        ),
    )


def _run_combat_normal_attacks(char: "BaseChar", duration: float, interval: float) -> None:
    deadline = char.now() + duration
    while char.now() < deadline:
        char.normal_attack()
        remaining = deadline - char.now()
        if remaining > 0:
            char.sleep(min(interval, remaining))


def _last_sound_dodge_time(char: "BaseChar") -> float:
    """Read the last completed sound-triggered dodge without coupling to trigger internals."""

    getter = getattr(getattr(char, "task", None), "last_dodge_time", None)
    if not callable(getter):
        return 0.0
    try:
        return max(0.0, float(getter()))
    except (TypeError, ValueError):
        return 0.0


def _flush_pending_sound_dodge(char: "BaseChar") -> None:
    """Execute a queued sound action so a phase-boundary dodge is visible immediately."""

    flush_pending_dodge = getattr(getattr(char, "task", None), "flush_pending_dodge", None)
    if callable(flush_pending_dodge):
        flush_pending_dodge()


def _sound_dodge_since(char: "BaseChar", recorded_at: float) -> tuple[bool, float]:
    _flush_pending_sound_dodge(char)
    current_at = _last_sound_dodge_time(char)
    return current_at > recorded_at, max(recorded_at, current_at)


def _run_normal_attacks_until_sound_dodge(
    char: "BaseChar",
    duration: float,
    interval: float,
    dodge_at: float,
) -> tuple[bool, float]:
    deadline = char.now() + duration
    while char.now() < deadline:
        char.normal_attack()
        dodged, dodge_at = _sound_dodge_since(char, dodge_at)
        if dodged:
            return True, dodge_at
        remaining = deadline - char.now()
        if remaining > 0:
            char.sleep(min(interval, remaining))
            dodged, dodge_at = _sound_dodge_since(char, dodge_at)
            if dodged:
                return True, dodge_at
    return False, dodge_at


def _run_zankou_dodge_recovery(
    char: "BaseChar",
    settings: CoordinatedAxisSettings,
    dodge_at: float,
) -> float:
    """Recover with normals; a new dodge restarts the configured recovery window."""

    deadline = char.now() + settings.zankou_dodge_normal_attack_duration
    while char.now() < deadline:
        char.normal_attack()
        dodged, dodge_at = _sound_dodge_since(char, dodge_at)
        if dodged:
            deadline = char.now() + settings.zankou_dodge_normal_attack_duration
            continue
        remaining = deadline - char.now()
        if remaining <= 0:
            continue
        char.sleep(min(settings.requiem_attack_interval, remaining))
        dodged, dodge_at = _sound_dodge_since(char, dodge_at)
        if dodged:
            deadline = char.now() + settings.zankou_dodge_normal_attack_duration
    return dodge_at


def _log_zankou_sound_dodge_recovery(char: "BaseChar", duration: float) -> None:
    logger = getattr(char, "logger", None)
    log_info = getattr(logger, "info", None)
    if callable(log_info):
        log_info(
            "zankou coordinated axis interrupted by sound dodge; "
            f"normal attacks for {duration:.2f}s before restarting"
        )


def perform_requiem_combat_axis(
    char: "BaseChar",
    context: "CombatContext",
    partner: "BaseChar",
) -> bool:
    """Run Requiem's no-resource field time, then request Zankou."""

    settings = coordinated_axis_settings(char)
    _run_combat_normal_attacks(
        char,
        settings.requiem_attack_duration,
        settings.requiem_attack_interval,
    )
    # MainDps normally keeps the current character until its field-time limit. Mark this
    # completed axis as an explicit departure until the public planner request resolves.
    char._coaxis_switch_pending = True
    context.request_switch(
        partner,
        reason="requiem coordinated axis complete",
        on_finish=lambda: setattr(char, "_coaxis_switch_pending", False),
    )
    return True


def perform_zankou_combat_axis(
    char: "BaseChar",
    context: "CombatContext",
    partner: "BaseChar",
) -> bool:
    """Run Zankou's field time; recover from a sound dodge by restarting the axis."""

    settings = coordinated_axis_settings(char)
    dodge_at = _last_sound_dodge_time(char)
    while True:
        # RU has already verified the switch and, for an intro, completed its entry recovery.
        char.heavy_attack(duration=settings.zankou_hold_duration)
        dodged, dodge_at = _sound_dodge_since(char, dodge_at)
        if not dodged:
            dodged, dodge_at = _run_normal_attacks_until_sound_dodge(
                char,
                settings.zankou_normal_attack_duration,
                settings.requiem_attack_interval,
                dodge_at,
            )
        if not dodged:
            context.request_switch(partner, reason="zankou coordinated axis complete")
            return True

        _log_zankou_sound_dodge_recovery(char, settings.zankou_dodge_normal_attack_duration)
        dodge_at = _run_zankou_dodge_recovery(char, settings, dodge_at)


class CoordinatedAxisIO(Protocol):
    def enabled(self) -> bool: ...

    def trigger_pressed(self, key: str) -> bool: ...

    def send_key(self, key: str) -> bool: ...

    def tap_attack(self) -> None: ...

    def attack_down(self) -> None: ...

    def attack_up(self) -> None: ...

    def log(self, message: str) -> None: ...


class RequiemZankouAxisTester:
    """Run a repeatable two-character input loop without using the combat planner."""

    POLL_INTERVAL = 0.02
    SWITCH_SETTLE_SECONDS = 0.15

    def __init__(self, io: CoordinatedAxisIO, settings: CoordinatedAxisSettings):
        self.io = io
        self.settings = settings
        self._trigger_was_down = True
        self._stop_requested = False

    def run(self) -> int:
        """Repeat rounds until the trigger is pressed again or the task is disabled."""

        while self.io.enabled() and self.io.trigger_pressed(self.settings.trigger_key):
            time.sleep(self.POLL_INTERVAL)
        if not self.io.enabled():
            return 0
        self._trigger_was_down = False
        rounds = 0
        self.io.log("安魂曲残虹合轴测试: 开始")
        try:
            if not self.io.send_key(self.settings.requiem_switch_key):
                return rounds
            if not self._wait(self.SWITCH_SETTLE_SECONDS):
                return rounds
            while self._should_continue():
                if not self.run_round():
                    break
                rounds += 1
        finally:
            self.io.attack_up()
            self.io.log(f"安魂曲残虹合轴测试: 停止, 完成{rounds}轮")
        return rounds

    def run_round(self) -> bool:
        """Run one Requiem attack window and one Zankou hold/tap window."""

        if not self._run_requiem_phase():
            return False
        if not self.io.send_key(self.settings.zankou_switch_key):
            return False
        if not self._wait(self.settings.zankou_switch_delay):
            return False

        self.io.attack_down()
        try:
            if not self._wait(self.settings.zankou_hold_duration):
                return False
        finally:
            self.io.attack_up()
        if not self._run_normal_attack_phase(self.settings.zankou_normal_attack_duration):
            return False
        if not self.io.send_key(self.settings.requiem_switch_key):
            return False
        return self._wait(self.SWITCH_SETTLE_SECONDS)

    def _run_requiem_phase(self) -> bool:
        return self._run_normal_attack_phase(self.settings.requiem_attack_duration)

    def _run_normal_attack_phase(self, duration: float) -> bool:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if not self._should_continue():
                return False
            attack_started = time.monotonic()
            self.io.tap_attack()
            remaining = deadline - time.monotonic()
            interval_left = self.settings.requiem_attack_interval - (
                time.monotonic() - attack_started
            )
            if remaining > 0 and interval_left > 0:
                if not self._wait(min(remaining, interval_left)):
                    return False
        return True

    def _wait(self, duration: float) -> bool:
        deadline = time.monotonic() + max(0.0, duration)
        while time.monotonic() < deadline:
            if not self._should_continue():
                return False
            time.sleep(min(self.POLL_INTERVAL, deadline - time.monotonic()))
        return self._should_continue()

    def _should_continue(self) -> bool:
        if self._stop_requested or not self.io.enabled():
            return False
        trigger_down = self.io.trigger_pressed(self.settings.trigger_key)
        if trigger_down and not self._trigger_was_down:
            self._stop_requested = True
            return False
        self._trigger_was_down = trigger_down
        return True
