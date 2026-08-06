"""[lw] Window foreground stabilization helper for background input delivery."""

import time
from collections.abc import Callable

STABLE_SETTLE_SECONDS = 0.5
STABLE_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.05


class WindowFocusStabilizer:
    """Track the target window's foreground state and wait until it has settled.

    Background automation posts input messages directly to the game window, so clicks
    work while the window is not in the foreground. However, the game can drop posted
    input while its real foreground state is changing (for example when the user
    Alt+Tabs to the window). Input should only be sent after the state has been stable
    for a short interval.
    """

    def __init__(
        self,
        is_foreground: Callable[[], bool],
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ):
        self._is_foreground = is_foreground
        self._sleep = sleep
        self._now = now
        self._visible: bool | None = None
        self._last_change = float("-inf")

    def observe(self, visible: bool) -> None:
        """Record an observed foreground state (used by the window monitor)."""
        visible = bool(visible)
        if self._visible is None:
            self._visible = visible
        elif visible != self._visible:
            self._visible = visible
            self._last_change = self._now()

    def stable(
        self,
        settle_seconds: float = STABLE_SETTLE_SECONDS,
        timeout_seconds: float = STABLE_TIMEOUT_SECONDS,
    ) -> bool:
        """Wait until the foreground state has been stable for settle_seconds.

        Returns False if the state kept changing until the timeout, True otherwise.
        """
        deadline = self._now() + timeout_seconds
        while True:
            self.observe(self._is_foreground())
            if self._now() - self._last_change >= settle_seconds:
                return True
            if self._now() >= deadline:
                return False
            self._sleep(POLL_INTERVAL_SECONDS)
