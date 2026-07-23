"""[lw] Minimal virtual Xbox controller support for coexistence testing."""

from __future__ import annotations

import time
from typing import Any


class VirtualGamepadUnavailableError(RuntimeError):
    """Raised when the optional virtual gamepad runtime cannot be initialized."""


class VirtualGamepadPulseTester:
    """Create one virtual Xbox controller and emit neutral-stick A-button pulses."""

    def __init__(self, gamepad_module: Any | None = None):
        self._gamepad_module = gamepad_module
        self._gamepad = None

    @property
    def connected(self) -> bool:
        return self._gamepad is not None

    def pulse_a(self, hold_seconds: float = 0.08) -> None:
        gamepad, gamepad_module = self._ensure_gamepad()
        button = gamepad_module.XUSB_BUTTON.XUSB_GAMEPAD_A
        try:
            gamepad.press_button(button=button)
            gamepad.update()
            time.sleep(max(0.01, float(hold_seconds)))
        finally:
            gamepad.release_button(button=button)
            gamepad.update()

    def close(self) -> None:
        gamepad = self._gamepad
        self._gamepad = None
        if gamepad is None:
            return
        gamepad.reset()
        gamepad.update()

    def _ensure_gamepad(self):
        if self._gamepad is not None:
            return self._gamepad, self._gamepad_module

        gamepad_module = self._gamepad_module
        if gamepad_module is None:
            try:
                import vgamepad as gamepad_module
            except (ImportError, OSError) as exc:
                raise VirtualGamepadUnavailableError(
                    "无法加载 vgamepad/ViGEmBus，请安装虚拟手柄运行库和驱动"
                ) from exc
            self._gamepad_module = gamepad_module

        try:
            gamepad = gamepad_module.VX360Gamepad()
            gamepad.reset()
            gamepad.update()
        except (OSError, RuntimeError) as exc:
            raise VirtualGamepadUnavailableError(
                "无法创建虚拟 Xbox 手柄，请确认 ViGEmBus 驱动已安装"
            ) from exc

        self._gamepad = gamepad
        return gamepad, gamepad_module
