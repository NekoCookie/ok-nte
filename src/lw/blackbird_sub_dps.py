"""[lw] Blackbird sub-DPS template and the Dark Star rounds of its team.

Team: Sakiri (buff), Blackbird (sub DPS), Requiem and Zankou (main DPS). Reactions follow
the element ring: Zankou/Sakiri -> Requiem trigger Scorch, Requiem <-> Blackbird trigger
Dark Star. Dark Star pays 20% of the damage recorded in its window.

Blackbird casts E whenever it is ready (Q1 -> Q2 -> E when her ultimate is up), and Sakiri
casts her Q as soon as it is ready. Only the main DPS ultimates wait, so they land inside
Dark Star and Sakiri's 20s ATK buff; once one of them is ready:

1. FLAME: when Zankou will cast his ultimate without stored flame (awakening 2/4, +150%),
   Zankou joins a Scorch with Requiem first. The first round always takes it from
   Zankou's combat-entry cycle.
2. SAKIRI: when Sakiri's buff is over (or about to be), Sakiri comes in and casts Q; if Q
   is not ready yet she normal-attacks and casts E on field until it is.
3. Inside a Dark Star window the ultimates go right away. Otherwise OPEN: Blackbird's next
   E swaps into Requiem and opens Dark Star; while that E is still cooling down
   (OPEN_WAIT) Requiem and Zankou keep their normal axis with the ultimates held.

Requiem's skills and Zankou's gold E wait only for the first Dark Star of a combat
(Zankou's awakening 5 fires once). The whole setup is capped.

The "黑羽副C打法" setting picks the opening (Sakiri first, or Zankou's gold E first) and
Blackbird's turn; the routing above is the same in every mode:

- Q1Q2E: Q1 -> Q2 -> E.
- E + Witch: Q2 first if the Witch form is still up; E unless her cycle is already full
  (a free full cycle); Q1 and a Witch turn until one enhanced E (capped). She leaves in
  Witch form, which pauses off field, and finishes it with Q2 next time.
"""

import time
from enum import Enum

from src.char.Blackbird import Blackbird
from src.combat.planner import FieldClaim, Planner
from src.lw.combat_test_policy import LWCombatTestPolicyMixin

MODE = "黑羽副C打法"
MODE_SAKIRI_OPENING = "早雾起手(黑羽Q1Q2E)"
MODE_ZANKOU_OPENING = "残虹黄E起手(黑羽Q1Q2E)"
MODE_SAKIRI_OPENING_WITCH = "早雾起手(黑羽E+魔女强化E)"
MODE_ZANKOU_OPENING_WITCH = "残虹黄E起手(黑羽E+魔女强化E)"
MODES = [
    MODE_SAKIRI_OPENING,
    MODE_ZANKOU_OPENING,
    MODE_SAKIRI_OPENING_WITCH,
    MODE_ZANKOU_OPENING_WITCH,
]
WITCH_MODES = frozenset({MODE_SAKIRI_OPENING_WITCH, MODE_ZANKOU_OPENING_WITCH})
ZANKOU_OPENING_MODES = frozenset({MODE_ZANKOU_OPENING, MODE_ZANKOU_OPENING_WITCH})
DARK_STAR_HOLD = "黯星期间不回黑羽(s)"
ROUND_SETUP = "黯星轮准备最长(s)"
SAKIRI_CHARGE = "早雾攒大招最长(s)"
ZANKOU_FLAME = "残虹大招前先拿蓄焰(2觉)"
WITCH_FIELD_LIMIT = "黑羽魔女形态站场上限(s)"
RELAY_INTRO_WAIT = "环合进场接力前等援护(s)"
KEYS = [
    MODE,
    DARK_STAR_HOLD,
    ROUND_SETUP,
    SAKIRI_CHARGE,
    ZANKOU_FLAME,
    WITCH_FIELD_LIMIT,
    RELAY_INTRO_WAIT,
]
# 黑羽副C配置的唯一默认值来源: 界面默认值和读不到配置时的兜底都读这里。
DEFAULTS = {
    MODE: MODE_ZANKOU_OPENING,
    DARK_STAR_HOLD: 10.0,
    ROUND_SETUP: 12.0,
    SAKIRI_CHARGE: 8.0,
    ZANKOU_FLAME: True,
    WITCH_FIELD_LIMIT: 5.0,
    # Estimate: the ring-entry support attack ends within the old 1.3s intro window.
    RELAY_INTRO_WAIT: 1.0,
}
SAKIRI_BUFF_DURATION = 20.0  # Sakiri Q: team ATK buff for 20s, paused by ultimate time stops
# Switching and Blackbird's E still take a few seconds before the ultimates go out.
SAKIRI_BUFF_MARGIN = 4.0


def configure_blackbird_sub_dps(task):
    task.default_config.update(DEFAULTS)
    task.config_type[MODE] = {"type": "drop_down", "options": MODES}
    task.config_description.update({
        MODE: (
            "切人路线相同, 只有黑羽上场放什么不同: Q1Q2E=Q1->Q2->E; "
            "E+魔女强化E=残留魔女先Q2, 自己环合没满先放普通E, 再Q1+魔女平A+1发强化E, "
            "带着魔女形态离场, 下次上场先Q2; "
            "残虹黄E起手受'开局残虹黄E后切辅助'和'黄E入场小怪也触发'开关控制"
        ),
        WITCH_FIELD_LIMIT: "E+魔女强化E: 魔女形态里放出1发强化E就走, 放不出来时最多站场这么久",
        RELAY_INTRO_WAIT: (
            "被环合进场只为接力的角色, 先等援护动画这么久(不平A)再切走; "
            "援护中切人游戏不接, 之后的按键会落到这个角色身上(安魂曲被误开大)"
        ),
        DARK_STAR_HOLD: (
            "黑羽触发黯星下场后至少这么久不再切回(扣除大招时停), 让主C打满两段黯星"
        ),
        ROUND_SETUP: (
            "安魂曲/残虹大招就绪后, 拿蓄焰/补早雾Q/等黑羽下一个E开黯星最多这么久(扣除大招时停), "
            "超时放开主C大招和切人限制, 按普通逻辑打"
        ),
        SAKIRI_CHARGE: (
            "主C大招就绪而早雾buff已过时, 早雾上场放Q; Q没好就留场平A+E攒, 最多这么久, "
            "超时不等早雾"
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


def config_mode(config) -> str:
    value = config.get(MODE) if config is not None else None
    return value if value in MODES else DEFAULTS[MODE]


class Step(Enum):
    INACTIVE = "inactive"  # no Blackbird sub-DPS teammate, or the skill test switch is on
    IDLE = "idle"  # no main DPS ultimate ready; Blackbird casts E whenever it is ready
    FLAME = "flame"
    SAKIRI = "sakiri"  # Sakiri's buff is over: she comes in for Q (charging it if needed)
    OPEN = "open"  # Blackbird E ready: she opens Dark Star now
    OPEN_WAIT = "open_wait"  # waiting for Blackbird's E cooldown, normal axis
    WINDOW = "window"  # inside the Dark Star windows after Blackbird's E
    LATE = "late"  # setup timed out: no holds


SETUP_STEPS = frozenset({Step.FLAME, Step.SAKIRI, Step.OPEN, Step.OPEN_WAIT})
ROUTED_STEPS = frozenset({Step.FLAME, Step.SAKIRI, Step.OPEN})


def team_blackbird(char) -> "BlackbirdSubDps | None":
    if isinstance(char, BlackbirdSubDps):
        return char
    for mate in getattr(getattr(char, "task", None), "chars", None) or ():
        if isinstance(mate, BlackbirdSubDps):
            return mate
    return None


def team_mode(char) -> str | None:
    """The configured Blackbird sub-DPS mode, or None without that template in the team."""

    blackbird = team_blackbird(char)
    return None if blackbird is None else config_mode(blackbird._lw_config())


def round_step(char) -> Step:
    blackbird = team_blackbird(char)
    return Step.INACTIVE if blackbird is None else blackbird.dark_star_step()


def dark_star_setup_pending(char) -> bool:
    """Whether a main DPS ultimate should wait for stored flame and Dark Star."""

    return round_step(char) in SETUP_STEPS


def dark_star_relay(char) -> bool:
    """A main DPS on field during round setup passes the round on without field time.

    While Zankou still needs stored flame, Zankou and Requiem keep their normal axis to
    fill a cycle and only leave once theirs is full, so the swap is the Scorch.
    """

    if not getattr(char, "is_current_char", False):
        return False
    step = round_step(char)
    if step not in ROUTED_STEPS:
        return False
    return step is not Step.FLAME or bool(char.is_cycle_full())


def wait_relay_intro(char) -> None:
    """Let the ring-entry support attack finish, silently, before a relay switches out.

    The game ignores a switch during that animation while the switch check falls back to
    the slot index, so the next character's inputs would land on this one.
    """

    blackbird = team_blackbird(char)
    config = blackbird._lw_config() if blackbird is not None else None
    duration = config_seconds(config, RELAY_INTRO_WAIT)
    char.logger.info(f"{char} relay entry waits {duration:.2f}s for the support attack")
    char.sleep(duration)


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


def preferred_reaction_target(source):
    """After the first round, Requiem banks Zankou's stored flame with her full cycle.

    Stored flame can be gathered before Zankou's ultimate is ready and one stack is
    enough, so a full Requiem cycle goes to Zankou whenever he has none; while
    Blackbird opens Dark Star the cycle still belongs to Blackbird.
    """

    blackbird = team_blackbird(source)
    if blackbird is None or source is not blackbird.team_requiem():
        return None
    step = blackbird.dark_star_step()
    if step is Step.SAKIRI:
        # Requiem's full cycle belongs to Blackbird (Dark Star) before Sakiri's Q.
        return blackbird
    # First round: Zankou's combat-entry cycle gives the flame, Requiem's goes to Blackbird.
    if not blackbird.dark_star_opened:
        return None
    if step in (Step.INACTIVE, Step.OPEN):
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
    if step not in ROUTED_STEPS:
        return True
    if char is blackbird.team_sakiri():
        # A full Requiem swaps into Blackbird first; switching to Sakiri would spend it.
        return step is Step.SAKIRI and not blackbird.requiem_cycle_full_on_field()
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
        relay = self.planner_action(
            tags={Planner.ActionTag.LEGACY_COMBO},
            slot=Planner.ActionSlot.LEGACY_COMBO,
            execute=lambda _: perform_dark_star_relay(self),
            name=f"{self}_dark_star_relay",
            reason="blackbird passes the round on to sakiri",
            priority_ready=lambda _: False,
        )
        claims = []
        if self.skill_available() and not self.lw_skills_disabled_for_test():
            claims.append(FieldClaim.normal(reason="sub dps dark star cycle"))

        def quick_turn():
            # Q1 -> Q2 -> E: the Witch form only lingers when Q2 did not come out, which
            # the turn remembers instead of reading the screen.
            if not self.in_ult and (yield ultimate):
                self.in_ult = True
                self._wait_for_second_ultimate()
            if self.in_ult and (yield ultimate.repeat_for_entry()):
                self.in_ult = False
            if (yield skill):
                self.stint_opens_dark_star = True

        def witch_turn():
            if self.in_ult and (yield ultimate):
                self.in_ult = False  # Q2 closes the Witch form kept from last time
            if self.is_cycle_full():
                self.stint_opens_dark_star = True  # E would only refill a full cycle
            elif (yield skill):
                self.stint_opens_dark_star = True
            if not self.in_ult and (yield ultimate.repeat_for_entry()):
                self.in_ult = True
                self.perform_in_ult(context, skill)

        def entry():
            self.stint_opens_dark_star = False
            if self.dark_star_step() is Step.SAKIRI:
                # Entered on Requiem's cycle: Q/E wait until Sakiri's buff is up.
                yield relay
                return
            yield from (witch_turn() if self.witch_mode() else quick_turn())

        return self.plan(skill, ultimate, claims=claims, entry=entry)

    def wait_intro(self, time_out=-1, click=True):
        """Cast Q1 right after the ring entry instead of the intro normal attacks."""

        step = self.dark_star_step() if self.has_intro else Step.INACTIVE
        if step is Step.SAKIRI:
            wait_relay_intro(self)  # only passing the round on to Sakiri
            return
        if step is not Step.INACTIVE:
            self.logger.info("blackbird ring entry goes straight to ultimate")
            return
        super().wait_intro(time_out=time_out, click=click)

    def witch_mode(self) -> bool:
        return config_mode(self._lw_config()) in WITCH_MODES

    def perform_in_ult(self, context, skill):
        """Witch turn: normal attacks until one enhanced E, capped.

        RU gates the enhanced E with the instant-cycle rule, so with a full cycle it never
        fires and Blackbird attacked for the whole Witch duration. The enhanced E is only
        test-mode gated here.
        """

        enhanced_skill = self.click_skill_action(
            name=f"{self}_witch_skill",
            add_tags=Planner.ActionTag.HIGH_PRIORITY,
            reason="blackbird witch enhanced skill",
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        limit = min(config_seconds(self._lw_config(), WITCH_FIELD_LIMIT), self.ULT_DURATION)
        self.logger.info(f"blackbird witch turn start, limit {limit:.1f}s")
        start = self.now()
        while (elapsed := self.now() - start) < limit:
            if elapsed > 1 and not self.ultimate_available(False):
                break
            if context.is_action_allowed(self, enhanced_skill) and self.click_skill():
                break
            self.normal_attack()
            self.sleep(0.1)
        self.logger.info(f"blackbird witch turn end {self.now() - start:.2f}s")

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
        """E whenever it is ready, except inside Dark Star and while the round is routed."""

        if self.is_current_char:
            return True
        step = self.dark_star_step()
        if step is Step.INACTIVE:
            return True
        if step is Step.SAKIRI:
            # Take a full Requiem's cycle (Dark Star) before Sakiri's Q.
            return self.requiem_cycle_full_on_field()
        return step in (Step.IDLE, Step.OPEN, Step.LATE) and bool(self.skill_available())

    def requiem_cycle_full_on_field(self) -> bool:
        requiem = self.team_requiem()
        return (
            requiem is not None
            and getattr(requiem, "is_current_char", False)
            and bool(requiem.is_cycle_full())
        )

    def wait_switch_cd(self):
        """The game only blocks switching back to the char just left; a relay leaves now."""

        if self.is_current_char and self.dark_star_step() is Step.SAKIRI:
            return
        super().wait_switch_cd()

    def dark_star_step(self) -> Step:
        """Current step of the team's Dark Star round, derived from what is observable."""

        if getattr(self, "is_dead", False) or self.lw_skills_disabled_for_test():
            return Step.INACTIVE
        config = self._lw_config()
        if self.is_current_char and self.round_start < 0:
            return Step.IDLE
        in_window = not self.is_current_char and self._elapsed(
            self.left_field_time
        ) < config_seconds(config, DARK_STAR_HOLD)
        # Both main DPS ultimates need cooldown and energy; the icon covers both.
        if not self._main_dps_ultimate_ready():
            self.round_start = -1.0
            self.sakiri_wait_start = -1.0
            return Step.WINDOW if in_window else Step.IDLE
        if self.round_start < 0:
            self.round_start = self._stamp()
            self.logger.info("dark star round start")
        if self._elapsed(self.round_start) >= config_seconds(config, ROUND_SETUP):
            return Step.LATE
        if config_enabled(config, ZANKOU_FLAME) and self._flame_needed():
            return Step.FLAME
        if self._sakiri_buff_short():
            if self.sakiri_wait_start < 0:
                self.sakiri_wait_start = self._stamp()
            if self._elapsed(self.sakiri_wait_start) < config_seconds(config, SAKIRI_CHARGE):
                return Step.SAKIRI
        else:
            self.sakiri_wait_start = -1.0
        if in_window:
            return Step.WINDOW
        return Step.OPEN if self.skill_available() else Step.OPEN_WAIT

    def _sakiri_buff_short(self) -> bool:
        """Whether Sakiri's ATK buff would be gone before the ultimates go out."""

        sakiri = self.team_sakiri()
        if sakiri is None:
            return False
        remaining = SAKIRI_BUFF_DURATION - self._elapsed(
            getattr(sakiri, "last_ultimate_time", -1.0)
        )
        return remaining < SAKIRI_BUFF_MARGIN

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
        if self.stint_opens_dark_star:
            # E filled the cycle and the swap into Requiem triggered Dark Star.
            self.left_field_time = self._stamp()
            self.round_start = -1.0
            if not self.dark_star_opened:
                self.logger.info("first dark star of the combat opened")
            self.dark_star_opened = True
        self.stint_opens_dark_star = False

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
        self.sakiri_wait_start = -1.0
        self.stint_opens_dark_star = False
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
