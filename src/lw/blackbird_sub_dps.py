"""[lw] Blackbird sub-DPS template and the Dark Star burst round of its team.

Team: Sakiri (buff), Blackbird (sub DPS), Requiem and Zankou (main DPS). Reactions follow
the element ring: Zankou/Sakiri -> Requiem trigger Scorch, Requiem <-> Blackbird trigger
Dark Star. Dark Star pays 20% of the damage recorded in its window, so each round lines the
main DPS ultimates up inside Dark Star and Sakiri's 20s ATK buff:

1. SAKIRI: Sakiri casts Q (she stays on field and charges it when the main DPS got there
   first). Her E is cast whenever it is ready.
2. FLAME: Zankou joins a Scorch with Requiem, so his next ultimate carries "stored flame"
   (awakening 2/4, +150%).
3. OPEN: Blackbird Q1 -> Q2 -> E, and the full cycle swaps into Requiem: Dark Star.
4. WINDOW: Requiem and Zankou ultimates. Blackbird stays off field for both Dark Star
   windows and returns once E and a main DPS ultimate are ready again.

Only the ultimates wait for the round. Requiem's skills and Zankou's gold E wait only for
the first Dark Star of a combat (Zankou's awakening 5 fires once). Every wait is capped.
"""

import time
from enum import Enum

from src.char.Blackbird import Blackbird
from src.combat.planner import FieldClaim, Planner
from src.lw.combat_test_policy import LWCombatTestPolicyMixin

DARK_STAR_HOLD = "黯星期间不回黑羽(s)"
ROUND_SETUP = "黯星轮准备最长(s)"
SAKIRI_CHARGE = "早雾攒大招最长(s)"
ZANKOU_FLAME = "残虹大招前先拿蓄焰(2觉)"
KEYS = [DARK_STAR_HOLD, ROUND_SETUP, SAKIRI_CHARGE, ZANKOU_FLAME]
# 黑羽副C配置的唯一默认值来源: 界面默认值和读不到配置时的兜底都读这里。
DEFAULTS = {
    DARK_STAR_HOLD: 10.0,
    ROUND_SETUP: 12.0,
    SAKIRI_CHARGE: 8.0,
    ZANKOU_FLAME: True,
}
# Sakiri's Q cast this long before the round started still counts for the round.
SAKIRI_RECENT_ULTIMATE = 5.0


def configure_blackbird_sub_dps(task):
    task.default_config.update(DEFAULTS)
    task.config_description.update({
        DARK_STAR_HOLD: (
            "黑羽触发黯星下场后至少这么久不再切回(扣除大招时停), 让主C打满两段黯星"
        ),
        ROUND_SETUP: (
            "一轮开始(黑羽E和安魂曲/残虹任一大招就绪)后, 早雾Q/残虹蓄焰/黑羽开黯星最多走这么久, "
            "超时放开主C大招和切人限制, 按普通逻辑打"
        ),
        SAKIRI_CHARGE: (
            "主C大招先好而早雾Q没好时, 早雾留场平A+E攒大招最多这么久, 超时跳过早雾直接开黯星"
        ),
        ZANKOU_FLAME: (
            "开=残虹大招前先让残虹环合安魂曲(浊燃)拿蓄焰(2觉/4觉增伤); 没有2觉就关"
        ),
    })


def config_seconds(config, key) -> float:
    value = config.get(key) if config is not None else None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULTS[key]


def config_enabled(config, key) -> bool:
    value = config.get(key) if config is not None else None
    return DEFAULTS[key] if value is None else bool(value)


class Step(Enum):
    INACTIVE = "inactive"  # no Blackbird sub-DPS teammate, or the skill test switch is on
    IDLE = "idle"  # waiting for Blackbird E and a main DPS ultimate
    SAKIRI = "sakiri"
    FLAME = "flame"
    OPEN = "open"
    WINDOW = "window"  # Dark Star windows after Blackbird's E
    LATE = "late"  # round setup timed out: no holds, Blackbird may still open


SETUP_STEPS = frozenset({Step.SAKIRI, Step.FLAME, Step.OPEN})


def team_blackbird(char) -> "BlackbirdSubDps | None":
    if isinstance(char, BlackbirdSubDps):
        return char
    for mate in getattr(getattr(char, "task", None), "chars", None) or ():
        if isinstance(mate, BlackbirdSubDps):
            return mate
    return None


def round_step(char) -> Step:
    blackbird = team_blackbird(char)
    return Step.INACTIVE if blackbird is None else blackbird.dark_star_step()


def dark_star_setup_pending(char) -> bool:
    """Whether a main DPS ultimate should wait for this round's Sakiri Q and Dark Star."""

    return round_step(char) in SETUP_STEPS


def dark_star_relay(char) -> bool:
    """A main DPS on field during round setup passes the round on without field time.

    While Zankou still needs stored flame, Zankou and Requiem keep their normal axis to
    fill a cycle and only leave once theirs is full, so the swap is the Scorch.
    """

    if not getattr(char, "is_current_char", False):
        return False
    step = round_step(char)
    if step not in SETUP_STEPS:
        return False
    return step is not Step.FLAME or bool(char.is_cycle_full())


def perform_dark_star_relay(char) -> bool:
    """Leave right away: the switch cooldown only blocks returning to the char just left."""

    char.logger.info(f"{char} relays the dark star round without field time")
    return True


def opening_burst_held(char) -> bool:
    """Whether Requiem's skills and Zankou's gold E wait for the combat's first Dark Star."""

    blackbird = team_blackbird(char)
    return (
        blackbird is not None
        and not blackbird.dark_star_opened
        and blackbird.dark_star_step() in SETUP_STEPS
    )


def sakiri_ultimate_held(char) -> bool:
    """Sakiri keeps her Q for the next round unless the round is waiting on it."""

    return round_step(char) not in (Step.INACTIVE, Step.SAKIRI, Step.LATE)


def preferred_reaction_target(source):
    """After the first round, Requiem banks Zankou's stored flame with her full cycle.

    Stored flame can be gathered before Zankou's ultimate is ready and one stack is
    enough, so a full Requiem cycle goes to Zankou whenever he has none; while
    Blackbird opens Dark Star the cycle still belongs to Blackbird.
    """

    blackbird = team_blackbird(source)
    if blackbird is None or source is not blackbird.team_requiem():
        return None
    # First round: Zankou's combat-entry cycle gives the flame, Requiem's goes to Blackbird.
    if not blackbird.dark_star_opened:
        return None
    if blackbird.dark_star_step() in (Step.INACTIVE, Step.OPEN, Step.SAKIRI):
        return None
    if not config_enabled(blackbird._lw_config(), ZANKOU_FLAME):
        return None
    zankou = blackbird.team_zankou()
    if zankou is None or getattr(zankou, "lw_stored_flame", False):
        return None
    return zankou


def round_allows_switch_in(char) -> bool:
    """Route each setup step to its character; outside a round nothing is restricted."""

    blackbird = team_blackbird(char)
    if blackbird is None or char is blackbird or getattr(char, "is_current_char", False):
        return True
    step = blackbird.dark_star_step()
    if step not in SETUP_STEPS:
        return True
    if char is blackbird.team_sakiri():
        return step is Step.SAKIRI
    if char is blackbird.team_zankou():
        return step is Step.FLAME
    if char is blackbird.team_requiem():
        # Requiem only takes the round from its own partner: Zankou while he gathers
        # stored flame (Sakiri keeps her cycle), Blackbird when Dark Star opens.
        current = blackbird.team_current()
        if step is Step.FLAME:
            return current is not None and current is blackbird.team_zankou()
        return step is Step.OPEN and current is blackbird
    return True


class BlackbirdSubDps(LWCombatTestPolicyMixin, Blackbird):
    """Short Blackbird turns that open Dark Star for the main DPS ultimates."""

    en_name = "Blackbird Sub DPS"
    cn_name = "黑羽副C"
    SECOND_ULTIMATE_WAIT = 1.5
    SECOND_ULTIMATE_POLL_INTERVAL = 0.1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reset_dark_star_state()

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action(
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        # Unlike RU, a full cycle does not hold E back: E also marks the target, and the
        # full cycle swaps to the reaction teammate either way.
        skill = self.click_skill_action(
            add_tags=Planner.ActionTag.HIGH_PRIORITY,
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        claims = []
        if self.skill_available() and not self.lw_skills_disabled_for_test():
            claims.append(FieldClaim.normal(reason="sub dps dark star cycle"))

        def entry():
            # Every turn is Q1 -> Q2 -> E, so the Witch form only lingers when Q2 did not
            # come out; the turn remembers that instead of reading the screen.
            self.stint_cast_skill = False
            if not self.in_ult and (yield ultimate):
                self.in_ult = True
                self._wait_for_second_ultimate()
            if self.in_ult and (yield ultimate.repeat_for_entry()):
                self.in_ult = False
            if (yield skill):
                self.stint_cast_skill = True

        return self.plan(skill, ultimate, claims=claims, entry=entry)

    def wait_intro(self, time_out=-1, click=True):
        """Cast Q1 right after the ring entry instead of the intro normal attacks."""

        if self.has_intro and self.dark_star_step() is not Step.INACTIVE:
            self.logger.info("blackbird ring entry goes straight to ultimate")
            return
        super().wait_intro(time_out=time_out, click=click)

    def _wait_for_second_ultimate(self) -> bool:
        deadline = self.now() + self.SECOND_ULTIMATE_WAIT
        while not self.ultimate_available():
            if self.now() >= deadline:
                self.logger.info("blackbird second ultimate unavailable; continuing with skill")
                return False
            self.normal_attack()
            self.sleep(self.SECOND_ULTIMATE_POLL_INTERVAL)
        return True

    def lw_can_switch_in(self):
        if self.is_current_char:
            return True
        return self.dark_star_step() in (Step.INACTIVE, Step.OPEN, Step.LATE)

    def dark_star_step(self) -> Step:
        """Current step of the team's Dark Star round, derived from what is observable."""

        if getattr(self, "is_dead", False) or self.lw_skills_disabled_for_test():
            return Step.INACTIVE
        config = self._lw_config()
        if self.is_current_char:
            return Step.OPEN if self.round_start >= 0 else Step.LATE
        if self._elapsed(self.left_field_time) < config_seconds(config, DARK_STAR_HOLD):
            self.round_start = -1.0
            return Step.WINDOW
        # Both main DPS ultimates need cooldown and energy; the icon covers both.
        if not self.skill_available() or not self._main_dps_ultimate_ready():
            self.round_start = -1.0
            return Step.IDLE
        if self.round_start < 0:
            self.round_start = self._stamp()
            self.logger.info("dark star round start")
        elapsed = self._elapsed(self.round_start)
        if elapsed >= config_seconds(config, ROUND_SETUP):
            return Step.LATE
        if elapsed < config_seconds(config, SAKIRI_CHARGE) and self._sakiri_needed():
            return Step.SAKIRI
        if config_enabled(config, ZANKOU_FLAME) and self._flame_needed():
            return Step.FLAME
        return Step.OPEN

    def _sakiri_needed(self) -> bool:
        sakiri = self.team_sakiri()
        if sakiri is None:
            return False
        cast_at = getattr(sakiri, "last_ultimate_time", -1.0)
        return cast_at < self.round_start - SAKIRI_RECENT_ULTIMATE

    def _flame_needed(self) -> bool:
        """Whether this round stops for Zankou's stored flame.

        The first round always takes it: Zankou's combat-entry cycle makes it one swap,
        and his off-field ultimate is not reliably readable right after combat starts.
        Later rounds only stop for it when Zankou casts his ultimate in the round.
        """

        zankou = self.team_zankou()
        if zankou is None or getattr(zankou, "lw_stored_flame", False):
            return False
        return not self.dark_star_opened or bool(zankou.ultimate_available())

    def _main_dps_ultimate_ready(self) -> bool:
        # The round is evaluated many times per planner pass; read the portraits once a frame.
        frame = getattr(self.task, "frame", None)
        if frame is not None and frame is self._main_ult_frame:
            return self._main_ult_ready
        ready = any(
            not getattr(char, "is_dead", False) and char.ultimate_available()
            for char in self.get_teammates_by_role(Planner.Role.MAIN_DPS)
        )
        self._main_ult_frame = frame
        self._main_ult_ready = ready
        return ready

    def _alive_mate(self, cls):
        for char in getattr(self.task, "chars", None) or ():
            if isinstance(char, cls) and char is not self and not getattr(char, "is_dead", False):
                return char
        return None

    def team_sakiri(self):
        from src.lw.combat_templates import SakiriBuffSupport

        return self._alive_mate(SakiriBuffSupport)

    def team_zankou(self):
        from src.lw.zankou_main_dps import ZankouMainDps

        return self._alive_mate(ZankouMainDps)

    def team_requiem(self):
        from src.char.Requiem import Requiem

        return self._alive_mate(Requiem)

    def team_current(self):
        for char in getattr(self.task, "chars", None) or ():
            if char is not None and getattr(char, "is_current_char", False):
                return char
        return None

    @staticmethod
    def _stamp() -> float:
        # Same clock as the freeze records behind time_elapsed_accounting_for_freeze.
        return time.time()

    def _elapsed(self, since: float) -> float:
        return self.time_elapsed_accounting_for_freeze(since)

    def switch_out(self):
        super().switch_out()
        if self.stint_cast_skill:
            # E filled the cycle and the swap into Requiem triggered Dark Star.
            self.left_field_time = self._stamp()
            self.round_start = -1.0
            if not self.dark_star_opened:
                self.logger.info("first dark star of the combat opened")
            self.dark_star_opened = True
        self.stint_cast_skill = False

    def reset_state(self):
        super().reset_state()
        self._reset_dark_star_state()

    _COMBAT_STATE_FIELDS = ("left_field_time", "round_start", "dark_star_opened", "in_ult")

    def lw_export_combat_state(self) -> dict:
        return {name: getattr(self, name) for name in self._COMBAT_STATE_FIELDS}

    def lw_import_combat_state(self, state: dict) -> None:
        for name in self._COMBAT_STATE_FIELDS:
            if name in state:
                setattr(self, name, state[name])

    def on_combat_end(self, chars):
        super().on_combat_end(chars)
        self._reset_dark_star_state()

    def _reset_dark_star_state(self):
        self.in_ult = False
        self.left_field_time = -1.0
        self.round_start = -1.0
        self.stint_cast_skill = False
        self.dark_star_opened = False
        self._main_ult_frame = None
        self._main_ult_ready = False

    def _lw_config(self):
        get_task_by_class = getattr(getattr(self, "task", None), "get_task_by_class", None)
        if not callable(get_task_by_class):
            return None

        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

        try:
            config_task = get_task_by_class(RequiemCombatConfigTask)
        except (LookupError, RuntimeError, TypeError):
            return None
        config = getattr(config_task, "config", None)
        return config if hasattr(config, "get") else None
