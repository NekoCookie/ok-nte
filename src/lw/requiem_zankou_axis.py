"""[lw] Standalone Requiem and Zankou coordinated-axis input test."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CoordinatedAxisSettings:
    trigger_key: str = "8"
    requiem_switch_key: str = "1"
    zankou_switch_key: str = "2"
    requiem_attack_interval: float = 0.2
    requiem_attack_duration: float = 2.0
    zankou_hold_duration: float = 2.0
    zankou_normal_attack_delay: float = 0.2


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
        if not self._wait(self.SWITCH_SETTLE_SECONDS):
            return False

        self.io.attack_down()
        try:
            if not self._wait(self.settings.zankou_hold_duration):
                return False
        finally:
            self.io.attack_up()
        if not self._wait(self.settings.zankou_normal_attack_delay):
            return False
        self.io.tap_attack()
        if not self.io.send_key(self.settings.requiem_switch_key):
            return False
        return self._wait(self.SWITCH_SETTLE_SECONDS)

    def _run_requiem_phase(self) -> bool:
        deadline = time.monotonic() + self.settings.requiem_attack_duration
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
