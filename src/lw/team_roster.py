"""LW 队伍变化确认与战斗队伍重载信号。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TeamRosterChange:
    """经过持续观测确认的队伍变化。"""

    kind: Literal["size", "signature"]
    expected_count: int
    observed_count: int
    detail: object | None = None

    def describe(self) -> str:
        if self.kind == "size":
            return f"team size changed {self.expected_count} -> {self.observed_count}"
        return "team signature changed"


class TeamReloadRequested(Exception):
    """中断基于旧队伍的动作，并请求战斗主循环重新加载角色。"""

    def __init__(self, change: TeamRosterChange):
        self.change = change
        super().__init__(change.describe())


class TeamRosterMonitor:
    """集中管理人数与头像签名的连续观测，吸收单帧 UI 抖动。"""

    def __init__(self):
        self._size_candidate: tuple[int, float] | None = None
        self._signature_candidate: tuple[object, float] | None = None

    def reset(self):
        self._size_candidate = None
        self._signature_candidate = None

    def clear_size(self):
        self._size_candidate = None

    def observe_size(
        self,
        *,
        expected_count: int,
        observed_count: int,
        now: float,
        confirm_interval: float,
        reliable_expansion: bool = True,
    ) -> tuple[str, TeamRosterChange | None]:
        if expected_count <= 0 or observed_count == expected_count:
            self.clear_size()
            return "stable", None

        if observed_count > expected_count and not reliable_expansion:
            self.clear_size()
            return "ignored_expansion", None

        previous = self._size_candidate
        if previous is None or previous[0] != observed_count:
            self._size_candidate = (observed_count, now)
            return "candidate", None

        if now - previous[1] < confirm_interval:
            return "pending", None

        self.clear_size()
        return (
            "confirmed",
            TeamRosterChange(
                kind="size",
                expected_count=expected_count,
                observed_count=observed_count,
            ),
        )

    def observe_signature(
        self,
        *,
        signature: object | None,
        expected_count: int,
        now: float,
        confirm_interval: float,
    ) -> tuple[str, TeamRosterChange | None]:
        if signature is None:
            self._signature_candidate = None
            return "stable", None

        previous = self._signature_candidate
        if previous is None or previous[0] != signature:
            self._signature_candidate = (signature, now)
            return "candidate", None

        if now - previous[1] < confirm_interval:
            return "pending", None

        self._signature_candidate = None
        return (
            "confirmed",
            TeamRosterChange(
                kind="signature",
                expected_count=expected_count,
                observed_count=expected_count,
                detail=signature,
            ),
        )
