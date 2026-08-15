"""LW-only Nanally ultimate behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.char.Nanally import Nanally

    _NanallyProxy = Nanally
else:

    class _NanallyProxy:
        pass


class NanallyExtMixin(_NanallyProxy):
    def lw_ultimate_action_landed(self, action_result: bool, was_available: bool) -> bool:
        """Accept an observed ultimate cooldown transition when animation detection is late."""

        return action_result or (was_available and not self.ultimate_available())

    def lw_should_continue_ultimate_field(self, _elapsed: float) -> bool:
        """Keep Nanally on field for the enclosing RU six-second ultimate window."""

        return True
