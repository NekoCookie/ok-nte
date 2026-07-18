import ctypes
import time

import cv2
import numpy as np
import win32con

from src.char.MainDps import MainDps
from src.combat import requiem_combo
from src.combat.planner import ActionSlot, ActionTag
from src.Labels import Labels
from src.sound_trigger.SoundCombatContext import SoundCombatContext


class _RequiemCombatIO:
    """实战里跑 4A跳A combo 的 io 适配器: 走框架后台 PostMessage(不动真实鼠键、游戏可不在前台)。
    should_continue 用廉价标志位判断"闪避待执行/已不是当前角色", 命中即中止本轮 combo, 把控制权
    交回战斗循环——待执行的闪避会在随后的 sleep_check 落地。intra-combo 用 raw sleep 保节奏。"""

    def __init__(self, char, dodge_react=False, watch_combat=False, task=None, round_seconds=0.0):
        self._char = char
        self.abort_reason = None  # should_continue 判 False 时记录原因, 供执行报告排查
        # dodge_react=True(闪避反击/双4a专用): 反击在处理"当前这次"闪避, combat_interrupt 仍为它
        # 而 set, 不能拿它判断; 只在"来了新的闪避在排队"(has_pending_action)时中止, 让位保命。
        self._dodge_react = dodge_react
        # watch_combat=True(仅主站场 combo): combo 中途每隔一段复查脱战, 目标死/打空立即收手,
        # 不再对着尸体空打完整轮。双4a 等精调时序段不开, 免插帧扰乱跳A时机。0=关(配置读不到默认)。
        # task: 本轮已抓好的"安魂曲配置"任务引用, 复查间隔/让路阈值都复用它, 不再各自 get_task_by_class。
        self._combat_check_interval = char._combo_combat_check_interval(task) if watch_combat else 0.0
        # combo 进度 < 此比例且技能/大招就绪就中断(让路去开)。0=关。round_seconds=这一轮预计总时长。
        self._break_for_skill_ratio = char._combo_break_for_skill_ratio(task) if watch_combat else 0.0
        self._round_seconds = round_seconds
        self._round_start = time.time()
        self._last_combat_check = self._round_start
        self._itx = char.task.executor.interaction
        try:
            cx = round(self._itx.capture.width * 0.5)
            cy = round(self._itx.capture.height * 0.5)
        except Exception:
            # capture 短暂无效(LauncherTask 刚切换 capture)时退回 task 宽高, 千万别退到
            # update_mouse_pos(-1,-1): interaction 刚重建时 bg_mouse_pos 是 (0,0)=窗口左上角,
            # combo 的左键会全部打空(实测: 重建后第一把双4a不出)。
            cx = round(getattr(char.task, "width", 0) * 0.5)
            cy = round(getattr(char.task, "height", 0) * 0.5)
        if cx > 0 and cy > 0:
            self._pos = self._itx.update_mouse_pos(cx, cy)
        else:
            self._pos = self._itx.update_mouse_pos(-1, -1)

    def should_continue(self):
        if not self._char.is_current_char:
            self.abort_reason = "已不是当前角色"
            return False
        if self._dodge_react:
            if SoundCombatContext().has_pending_action():
                self.abort_reason = "新声音闪避排队"
                return False
            return True
        if SoundCombatContext.should_interrupt_combat():
            self.abort_reason = "声音打断信号"
            return False
        # 主站场 combo: 每隔 _combat_check_interval 复查一次脱战(刷新一帧 + 带去抖的 in_combat)。
        # 目标已死/打空则抛 NotInCombat 收手, 不再把这一整轮 raw-sleep combo 打完(对着尸体空打)。
        # should_continue 恒在"鼠标已抬起"时被调用, 此处抛异常不会留下按住的左键。
        if self._combat_check_interval > 0:
            now = time.time()
            if now - self._last_combat_check >= self._combat_check_interval:
                self._last_combat_check = now
                self._char._check_combat_alive()
                # 为技能/大招让路: combo 进度还没过阈值(伤害大头在结尾, 过半就打完不打断),
                # 且此刻技能/大招已就绪 → 中断本轮, 交回 do_perform 顶部去开(下一次 do_perform
                # 重新决策会 click_ultimate / cast skill)。恒在"鼠标已抬起"时判断, 中止安全。
                if self._break_for_skill_ratio > 0 and self._round_seconds > 0:
                    progress = (now - self._round_start) / self._round_seconds
                    if progress < self._break_for_skill_ratio and self._char._skill_or_ult_ready():
                        self._char.logger.info(
                            f"combo 进度 {progress:.0%}<{self._break_for_skill_ratio:.0%} 且技能/大招就绪, "
                            f"中断本轮 combo 去开")
                        self.abort_reason = "让位技能/大招"
                        return False
        return True

    def mouse_down(self):
        self._itx.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, self._pos)

    def mouse_up(self):
        self._itx.post(win32con.WM_LBUTTONUP, 0, self._pos)

    def space_down(self):
        self._itx.send_key_down("space")

    def space_up(self):
        self._itx.send_key_up("space")

    def sleep_ms(self, ms):
        time.sleep(ms / 1000.0)


class Requiem(MainDps):
    """Main DPS template with off-field skill overlap after skill cast."""

    # 主C站场输出改用一轮 4A跳A combo(时序见 requiem_combo, 与跳A宏方案一同源)。
    # idle 原来是 2.5s 连点; 按需求改成"刚好打一轮"的时长。
    IDLE_ATTACK_DURATION = requiem_combo.scheme_a_round_seconds()
    # combo 伤害大头在结尾, 不打完丢很多伤害 → 只有技能"很快就绪"(剩余CD < 1s)才不开整轮、
    # 改成 0.1 间隔平A盯着就绪; >= 1s 一律走完整轮 combo(输出不亏)。
    IDLE_NEAR_SKILL_CD = 1.0
    IDLE_NEAR_SKILL_INTERVAL = 0.1
    # combo 中途每隔这么久复查一次脱战(目标死/打空即收手, 不空打整轮)。配置读不到时用; 0=关。
    COMBO_COMBAT_CHECK_INTERVAL = 0.5
    # combo 进度 < 此比例且技能/大招就绪 → 中断本轮 combo 交回主循环去开(伤害大头在结尾, 过半就打完)。
    # 配置读不到时用; 0=关(永不为技能中断)。
    COMBO_BREAK_FOR_SKILL_RATIO = 0.5
    # 闪避反击: 触发闪避后强制平A的默认秒数(配置读不到时用)与点击间隔。
    # 实际秒数在安魂曲战斗配置任务(RequiemCombatConfigTask)里可配, 便于实时调。
    DODGE_COUNTER_ATTACK = 0.3
    DODGE_COUNTER_INTERVAL = 0.1
    DODGE_KEY = "lshift"  # 游戏闪避键
    DODGE_DIR_KEY = "w"   # 双4a尾段"带方向闪避"的方向键: 按住W再按闪避
    # 双4a"窗口内"部分时长(ms): 前段平A的前这么久在 execute_dodge 里打(立即反击+填满声音1秒去抖窗口),
    # 之后 execute_dodge 返回、"处理这次闪避"结束, 剩余部分交 do_perform 无缝续打(可被新声音打断)。
    DODGE_WINDOW_FILL_MS = 1000
    # combo 起手前, 若紧接在闪避反击之后, 额外等这么久让反击后摇走完再落第一下(否则 combo 顺序乱)。
    # 只加在 combo 路径; 切人/技能/大招不等→立即执行取消后摇。默认值, 4A 任务里可配。
    DODGE_COUNTER_COMBO_WAIT = 0.3

    SKILL_OFF_FIELD_DURATION = 3.0
    REAL_SKILL_CD = 16.0  # 真技能固定16s CD(从释放起算);免费技能不影响, 不锚。
    # 真技能(伤害大头)放招瞬间常被闪避打断、按键没进CD。被打断后继续平A(打出闪避反击)
    # 并反复重试放招的最长时间; 超时仍没放进就本轮放弃, 下轮再试。不死等。
    REAL_SKILL_RETRY_MAX_DURATION = 3.0
    # 区分"真放成功的长CD(16s)" vs "被闪避打断的假成功短CD(~3s)"的阈值。
    # 进CD但<此值 = 被打断、没真放成, 不该 overlap 下场。
    REAL_SKILL_LANDED_MIN_CD = 8.0
    # 真技能按键后, 技能图标上的 CD 数字有约 1s 滞后才从"就绪/0"刷到 16。若按键后瞬读
    # 一次就定生死, 数字没刷出来时会把"放成功"误当失败漏切(实测12次里漏切3次)。
    # 故按键后在此窗口内轮询确认: 一读到长CD 立即判成功提前结束, 不必等满。
    REAL_SKILL_LANDED_CONFIRM_WINDOW = 0.5
    REAL_SKILL_LANDED_POLL_INTERVAL = 0.1
    PRE_SKILL_ULTIMATE_WAIT = 0.3
    # 真技能放出"之前"先平A出手进入交战。开战瞬间安魂曲还没真正攻击,
    # 直接放技能会打空(技能消失);先平A一下交战,技能才稳。与切人时机无关。
    # 只在"真技能"分支生效;免费技能是中途放的(已交战),不需要。可被配置覆盖。
    SKILL_ENGAGE_ATTACK = 0.1
    CONF_ENGAGE_ATTACK = "安魂曲技能前平A(s)"
    # 技能图标模板:真技能 / 免费技能图标长得不一样,直接用模板匹配区分。
    # 这是唯一判据(不再用时间锚点——时间猜在免费技能拖过16s时必然判反,
    # 反而是 bug 源头)。识别不到时按真技能处理(见 is_real_skill_now)。
    SKILL_REAL_TEMPLATE_PATH = "assets/images/requiem_skill_real.png"
    SKILL_FREE_TEMPLATE_PATH = "assets/images/requiem_skill_free.png"
    SKILL_VISUAL_MIN_CONF = 0.45   # 两个模板都低于此 → 没识别到
    SKILL_VISUAL_MARGIN = 0.06     # 两者差距小于此 → 分不清
    FREE_SKILL_ATTACK_INTERVAL = 0.1
    FREE_SKILL_FOLLOWUP_ATTACK_DURATION = 0.85
    # 免费技能后普攻会顺出又慢又低伤的第五下平A(a5); 放完免费技能用闪避打断它(实测只有闪避能打断,
    # 跳A打不断)、不打那第五下, 直接接后续输出。以下为打断时序默认值(ms, 配置读不到时用); hold<=0=关(不打断)。
    FREE_BREAK_DELAY_MS = 250
    FREE_BREAK_JUMP_HOLD_MS = 20
    FREE_BREAK_WAIT_MS = 400

    _skill_real_template = None
    _skill_free_template = None
    _skill_templates_loaded = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill_off_field_until = 0.0
        self._dodge_counter_at = 0.0  # 上次闪避反击出手时刻(供 combo 起手前等后摇)
        self._pending_double_4a = None   # 非None=双4a窗口外部分待续打(do_perform顶上处理)
        self._d4_front_left_ms = 0.0     # 双4a前段平A在窗口内打掉后剩余的时长(ms)
        self._d4_seam_t = 0.0            # 窗口内结束时刻(单调时钟), 供诊断续打接缝
        self._d4_last_end = 0.0           # 上轮双4a结束时刻(单调时钟), 供诊断 combo 交接

    def describe_role(self):
        # 无辅助体系(队友是娜娜莉等上游原生角色)时: 用 RU 安魂曲(Lacrimosa)的角色画像
        # (MAIN_DPS), 否则 planner 按 BaseChar 默认把本角色当 sub_dps, 主从关系全反
        # (实测: 与娜娜莉双排时 planner 乒乓空切, 双方都放不出招)。体系内维持现状。
        if not self.team_has_support_template():
            from src.char.Lacrimosa import Lacrimosa

            return Lacrimosa.describe_role(self)
        return super().describe_role()

    def combat_plan(self, context):
        # 无辅助体系(经 lw_use_do_perform 退回 planner)时: 整体用 RU 安魂曲的出招计划。
        if not self.team_has_support_template():
            from src.char.Lacrimosa import Lacrimosa

            return Lacrimosa.combat_plan(self, context)
        # 有辅助体系: 安魂曲双4a 的 planner 计划(不走 super()=MainDps 的通用 idle 平A)。
        return self._lw_combat_plan(context)

    def _lw_combat_plan(self, context):
        """安魂曲双4a 迁 planner(对照 do_perform, ru 风格): 大招/真技能/免费技/双4a combo/
        窗口外续打 各是独立声明动作, execute 复用现有方法(combo 时序、cast_real_skill、续打状态机
        一行不改), entry generator 编排 do_perform 的分支顺序。双4a 是原子动作、整段包进一个
        LEGACY_COMBO action(planner 为 combo 迁移预留的槽), 不拆内部跳A时序。"""
        ultimate = self.planner_action(
            tags={ActionTag.ULTIMATE_ACTION},
            slot=ActionSlot.ULTIMATE,
            execute=lambda _: self.click_ultimate(wait_if_no_cd=self.PRE_SKILL_ULTIMATE_WAIT),
            name=f"{self}_ultimate",
            reason="requiem ultimate ready",
            can_execute=lambda _: self.ultimate_available(),
            priority_ready=lambda _: self.ultimate_available(),
        )
        real_skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION, ActionTag.DAMAGE},
            slot=ActionSlot.SKILL,
            execute=lambda _: self.cast_real_skill(),
            name=f"{self}_real_skill",
            reason="requiem real skill (damage)",
            can_execute=lambda _: self.skill_available() and self.is_real_skill_now(),
            priority_ready=lambda _: self.skill_available(),
        )
        free_skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=self._execute_free_skill,
            name=f"{self}_free_skill",
            reason="requiem free skill",
            can_execute=lambda _: self.skill_available() and not self.is_real_skill_now(),
            priority_ready=lambda _: False,  # 免费技中途放, 不主动抢切人
        )
        combo = self.planner_action(
            tags={ActionTag.LEGACY_COMBO, ActionTag.DAMAGE, ActionTag.FIELD_TIME},
            slot=ActionSlot.LEGACY_COMBO,
            execute=lambda _: self.idle_normal_attack(),
            name=f"{self}_double_4a",
            reason="requiem double-4a combo",
            priority_ready=lambda _: False,  # combo 靠 field_time 站场, 不主动抢切人
        )
        combo_continue = self.planner_action(
            tags={ActionTag.LEGACY_COMBO},
            slot=ActionSlot.LEGACY_COMBO,
            execute=lambda _: self._run_double_4a_outside(),
            name=f"{self}_double_4a_continue",
            reason="requiem double-4a outside-window continuation",
            can_execute=lambda _: self._pending_double_4a is not None,
            priority_ready=lambda _: False,
        )

        def entry():
            # 续打窗口外部分优先: 闪避那1秒窗口已在 execute_dodge 打了前段前半, 这里无缝接剩余,
            # 跳过技能OCR(免在双4a中间插延迟打乱节奏)。对应 do_perform 顶部的 _pending 分支。
            if self._pending_double_4a is not None:
                yield combo_continue
                return
            # 测试开关: 禁用技能大招, 只站场打 combo(单独测手感/闪避)
            if self._skills_disabled_for_test():
                yield combo
                return
            # 目标存活门: 别对尸体开大或放真技能(白扔长CD); 已脱战抛 NotInCombat 收手
            self._check_combat_alive()
            used_ultimate = bool((yield ultimate))
            if self.skill_available():
                if self.is_real_skill_now():
                    yield real_skill  # 真技能是伤害大头: 放进CD才 overlap
                    return
                elif bool((yield free_skill)):
                    return  # 免费技: 留场接平A
            if used_ultimate:
                return
            yield combo  # 双4a

        return self.plan(
            ultimate, real_skill, free_skill, combo, combo_continue, entry=entry
        )

    def _execute_free_skill(self, context=None):
        """免费技动作(对应 do_perform 的免费技分支): 放招→闪避打断拖沓的a5→后续输出。"""
        if self.click_skill(time_out=1.0):
            self.logger.info("requiem FREE skill cast, staying on field")
            self._free_skill_break_a5()
            self.free_skill_followup_attack()
            return True
        return False

    def should_force_off_field(self):
        return time.time() < self.skill_off_field_until

    @classmethod
    def _load_skill_templates(cls):
        if not cls._skill_templates_loaded:
            cls._skill_templates_loaded = True
            cls._skill_real_template = cv2.imread(cls.SKILL_REAL_TEMPLATE_PATH)
            cls._skill_free_template = cv2.imread(cls.SKILL_FREE_TEMPLATE_PATH)
        return cls._skill_real_template, cls._skill_free_template

    @staticmethod
    def _template_conf(crop_bgr, template_bgr):
        """灰度归一化相关匹配,返回 [-1,1] 置信度。模板与裁剪同尺寸即逐像素相关。"""
        cg = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        tg = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if tg.shape != cg.shape:
            tg = cv2.resize(tg, (cg.shape[1], cg.shape[0]))
        return float(cv2.matchTemplate(cg, tg, cv2.TM_CCOEFF_NORMED).max())

    def _decide_skill_kind(self, conf_real, conf_free):
        """根据两模板置信度判定:'real' / 'free' / None(不可靠,需回退时间)。"""
        if max(conf_real, conf_free) < self.SKILL_VISUAL_MIN_CONF:
            return None
        if abs(conf_real - conf_free) < self.SKILL_VISUAL_MARGIN:
            return None
        return "free" if conf_free > conf_real else "real"

    def classify_skill_visual(self):
        """用技能图标模板匹配判定当前是真技能还是免费技能。
        返回 'real' / 'free' / None(识别不可靠或出错,调用方回退到时间锚点)。"""
        try:
            real_tpl, free_tpl = self._load_skill_templates()
            if real_tpl is None or free_tpl is None:
                return None
            crop = self.task.get_box_by_name(Labels.box_skill).crop_frame(self.task.frame)
            if crop is None or crop.size == 0:
                return None
            conf_real = self._template_conf(crop, real_tpl)
            conf_free = self._template_conf(crop, free_tpl)
            kind = self._decide_skill_kind(conf_real, conf_free)
            self.logger.info(
                f"requiem skill icon match real={conf_real:.3f} free={conf_free:.3f} "
                f"-> {kind or 'unknown(treat as real)'}"
            )
            return kind
        except Exception as e:
            self.logger.info(f"requiem skill visual classify failed, treat as real: {e}")
            return None

    def is_real_skill_now(self):
        """这一发是不是真技能:只看技能图标。识别不到(None)就按真技能处理——
        宁可把免费误当真(只是少留一会场,代价小),也不能把真当免费漏切(那才是 bug)。"""
        return self.classify_skill_visual() != "free"

    def engage_attack_duration(self):
        """真技能前的起手平A时长, 读"安魂曲配置"任务(RequiemCombatConfigTask)的配置, 便于实时调。"""
        return self._read_jump_task_conf(self.CONF_ENGAGE_ATTACK, self.SKILL_ENGAGE_ATTACK)

    def engage_before_skill(self, duration):
        """真技能前的起手平A:用无守卫的 normal_attack 直接出手进入交战。

        不用 continues_normal_attack/fill_idle_attack —— 后者在开战瞬间会被
        in_animation / current_char 守卫挡掉,导致一次都不点(技能打空)。
        保证至少出手一次,并打印实际次数便于排查。
        """
        start = time.time()
        n = 0
        while True:
            self.normal_attack()
            n += 1
            if time.time() - start >= duration:
                break
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)
        self.logger.info(f"requiem pre-skill engage: {n} normal attack(s) over {duration:.2f}s")

    def _jump_task(self):
        """取"安魂曲配置"任务(RequiemCombatConfigTask)实例, 拿不到返回 None。
        实战直接复用该任务的方案选择/参数构建方法, 保证与测试同一套逻辑同一份配置。"""
        try:
            from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
            return self.task.get_task_by_class(RequiemCombatConfigTask)
        except Exception as e:
            self.logger.debug(f"get jump task failed: {e}")
            return None

    def _run_configured_combo(self, io, task=None):
        """按"安魂曲配置"的「4A宏模式」跑一轮 combo(方案一/二/三/四共用同一处选择, 复用 jump 任务的
        _scheme_runner, 时序/参数与测试一致)。拿不到配置或原始录制等无对应方案时回退方案一。
        不管哪套方案, should_continue 都是每下点击前查(光速4a≈40ms/次, 让路比方案一还快),
        执行仍由 combo_attack 尾部的 sleep_check 统一兜底。"""
        from src.combat.BaseCombatTask import NotInCombatException
        if task is None:
            task = self._jump_task()
        if task is not None:
            try:
                mode = task.config.get(task.CONF_MACRO_MODE, task.MODE_SCHEME_A)
                runner = task._scheme_runner(mode, io)
                if runner is not None:
                    runner[0]()
                    return
            except NotInCombatException:
                raise  # 脱战(combo中途打空/目标死)必须一路抛到战斗循环收手, 别被下面的兜底吞掉
            except Exception as e:
                self.logger.debug(f"configured combo failed, fallback scheme_a: {e}")
        requiem_combo.run_scheme_a(io)

    def combo_attack(self):
        """主C的普通攻击 = 跑一轮 combo, 走哪套复用"安魂曲配置"的「4A宏模式」(方案一/二/三/四)。
        走后台 PostMessage; 提 1ms 定时精度 + raw sleep 保节奏(self.sleep 会插帧截图, 打乱 combo);
        每一下之前查 should_continue, 闪避待执行/已切走即中止, 交回战斗循环让闪避随后落地。"""
        self.check_combat()  # 战斗已结束/切队则抛出, 不空打一轮
        self._wait_dodge_counter_recovery()  # 若紧接闪避反击, 先等其后摇再起 combo(顺序不乱)
        # 诊断: 双4a刚结束就接站场combo时记录交接间隔(排查"双4a错位带歪后续连招"用)
        d4_last_end = getattr(self, "_d4_last_end", 0.0)
        if d4_last_end > 0:
            d4_gap = time.perf_counter() - d4_last_end
            if d4_gap < 3:
                self.logger.info(f"双4a结束后 {d4_gap:.2f}s 起手站场combo")
        # 本轮抓一次"安魂曲配置"任务引用: 脱战复查间隔 / 让路阈值 / 一轮预计时长都复用它,
        # 不再各自 get_task_by_class(线性扫任务表)。拿不到就用方案一固定时长兜底。
        task = self._jump_task()
        round_seconds = (task.scheme_round_seconds() if task is not None
                         else requiem_combo.scheme_a_round_seconds())
        io = _RequiemCombatIO(self, watch_combat=True, task=task, round_seconds=round_seconds)
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self._run_configured_combo(io, task)
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
        # combo 一轮内用 raw sleep(不插帧保节奏), 全程不走 sleep_check; 而排队的声音闪避只在
        # sleep_check 里落地。若不补这一下, 闪避被 should_continue 中止 combo 后, 主循环在
        # "读CD→combo(立即返回)"间空转、始终不执行那次闪避 → 排队1s超时被丢(实测爆发期不闪避)。
        # 故每轮结束(或被闪避中止返回)后补一次 sleep_check: 有待执行的救命闪避立即落地(与老版
        # 连点每0.1s一次sleep_check同效), 只加在轮与轮之间, 不打乱单轮 combo 节奏。
        self.task.sleep_check()

    def _read_jump_task_conf(self, key, default, task=None):
        """读安魂曲战斗配置任务(RequiemCombatConfigTask)的某个数值配置(可实时调), 读不到用默认。
        传入 task 则复用它(本轮已抓好), 不再 get_task_by_class 重复扫任务表。"""
        try:
            if task is None:
                from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
                task = self.task.get_task_by_class(RequiemCombatConfigTask)
            if task is not None:
                return max(0.0, float(task.config.get(key, default)))
        except Exception as e:
            self.logger.debug(f"read jump task config {key} failed: {e}")
        return default

    def _combo_combat_check_interval(self, task=None):
        """combo 中途脱战复查间隔(秒), 从"安魂曲配置"读, 可实时调; 0=关。默认 COMBO_COMBAT_CHECK_INTERVAL。"""
        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
        return self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_COMBO_COMBAT_CHECK, self.COMBO_COMBAT_CHECK_INTERVAL, task=task)

    def _combo_break_for_skill_ratio(self, task=None):
        """combo 为技能/大招让路的进度阈值(0~1): 进度<此值且技能/大招就绪就中断本轮 combo 去开。
        "禁用技能大招(测试)"开着时只站场, 直接返回 0 不让路。0=关(永不为技能中断)。"""
        if self._skills_disabled_for_test(task):
            return 0.0
        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
        return self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_COMBO_BREAK_FOR_SKILL,
            self.COMBO_BREAK_FOR_SKILL_RATIO, task=task)

    def _skill_or_ult_ready(self):
        """combo 中途: 大招或技能是否已就绪(值得中断 combo 让路去开)。读缓存CD/就绪判定, 不贵。"""
        try:
            if self.ultimate_available():
                return True
            return self.skill_available()
        except Exception:
            return False

    def _check_combat_alive(self):
        """刷新一帧并复查是否仍在战斗; 已脱战(打空/目标死)则抛 NotInCombatException 收手。
        复用框架带去抖(2帧miss+0.4s settle)的 in_combat 判定, 不会因血条/目标框闪一下误停。
        combo 中途(每约0.5s)与放技能/大招前各调一次, 免得对着尸体空打整轮或空放大招/技能。"""
        self.task.next_frame()
        self.task.check_combat()

    def _dodge_counter_duration(self):
        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
        return self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_DODGE_COUNTER, self.DODGE_COUNTER_ATTACK)

    def _dodge_counter_combo_wait(self):
        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
        return self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_DODGE_COMBO_WAIT, self.DODGE_COUNTER_COMBO_WAIT)

    def _active_dodge(self):
        """主动按一下游戏闪避键(lshift): 取消上一段(反击)后摇, 干净衔接后续 combo
        (否则反击后接平A会变5a、不接又原地发呆)。就是按一下键盘 shift, 不涉及声音。"""
        try:
            self.task.send_key(self.DODGE_KEY, down_time=0.02)
        except Exception as e:
            self.logger.debug(f"active dodge failed: {e}")

    def _directional_dodge(self):
        """带方向的闪避: 按住W再按闪避, 稍顿再一起松(和"安魂曲配置"双4a尾段一致)。"""
        try:
            self.task.send_key_down(self.DODGE_DIR_KEY)
            self.task.send_key_down(self.DODGE_KEY)
            time.sleep(0.05)
            self.task.send_key_up(self.DODGE_KEY)
            self.task.send_key_up(self.DODGE_DIR_KEY)
        except Exception as e:
            self.logger.debug(f"directional dodge failed: {e}")

    def _dodge_double_4a_inside(self, task):
        """双4a 的"窗口内"部分(跑在 execute_dodge 里): 只打前段平A 的前 ~1 秒, 填满声音那 1 秒去抖
        窗口(这 1 秒新攻击本就被去抖丢、打得安心, 且是立即反击)。然后挂起 _pending_double_4a,
        execute_dodge 就此返回——"处理这次闪避"真的结束了。剩余部分(前段剩余→跳A→后段→尾段闪避→
        补平A)交 do_perform 顶上无缝续打, 那部分是普通 combo, 被新声音打断时新闪避经正常路径触发
        自己的新一轮反击, 不再和这次闪避耦合。"""
        front_ms = task._conf_num(task.CONF_D4_FRONT, 950)
        inside_ms = min(front_ms, self.DODGE_WINDOW_FILL_MS)
        io = _RequiemCombatIO(self, dodge_react=True)  # 窗口内新攻击排不进队, dodge_react 不会误停
        t0 = time.perf_counter()
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            clicks, aborted = requiem_combo._fill_attacks(io, inside_ms,
                                        task._conf_num(task.CONF_D4_CLICK_HOLD, 40),
                                        task._conf_num(task.CONF_D4_CLICK_GAP, 8))
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
        self.logger.info(
            f"双4a窗口内报告: 标称{inside_ms:.0f}ms 实际{(time.perf_counter() - t0) * 1000:.0f}ms "
            f"{clicks}点"
            f"{f' 中止({io.abort_reason})' if aborted else ''}"
        )
        self._d4_front_left_ms = max(0.0, front_ms - inside_ms)
        self._d4_seam_t = time.perf_counter()  # 记窗口内结束时刻, 供续打测接缝延迟
        self._pending_double_4a = task     # 交给 do_perform 顶上续打
        self._dodge_counter_at = 0.0

    def _run_double_4a_outside(self):
        """双4a 的"窗口外"部分(跑在主循环 do_perform 顶上, 像普通 combo 一样可被新声音打断):
        前段剩余 → 跳A(续段, 第二个4a) → 后段平A → 尾段闪避 → 补平A。用普通 io: 新声音置 combat_interrupt
        即中止 → 交回主循环, sleep_check 执行那次新闪避(→ 它自己的新一轮双4a)。"""
        task = self._pending_double_4a
        self._pending_double_4a = None
        if task is None:
            return
        seam_ms = (time.perf_counter() - self._d4_seam_t) * 1000
        self.logger.info(f"安魂曲双4a: 窗口内→续打 接缝延迟 {seam_ms:.0f}ms")
        p = dict(task._scheme_d4_params())
        p["front_ms"] = getattr(self, "_d4_front_left_ms", 0.0)  # 前段只打剩余(前~1秒已在窗口内打过)
        io = _RequiemCombatIO(self)  # 普通io: 新声音即中止(和 combo 一致)
        rep = None
        tail_dodge = tail_clicks = tail_aborted = None
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            rep = requiem_combo.run_scheme_double_4a(io, **p)  # 前段剩余 → 跳A → 后段
            if io.should_continue():
                if task.config.get(task.CONF_D4_TAIL_DODGE, task.D4_DODGE_W) == task.D4_DODGE_JUMP:
                    io.space_down()
                    io.mouse_down()
                    io.sleep_ms(task._conf_num(task.CONF_LS_JUMP_HOLD, 18))
                    io.mouse_up()
                    io.space_up()
                    tail_dodge = "跳+左键"
                else:
                    self._directional_dodge()
                    tail_dodge = "W+闪避"
                tail_clicks, tail_aborted = requiem_combo._fill_attacks(
                    io, task._conf_num(task.CONF_D4_TAIL_FILL, 350),
                    task._conf_num(task.CONF_LS_CLICK_HOLD, 40),
                    task._conf_num(task.CONF_LS_CLICK_GAP, 8))
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
        self._log_d4_outside_report(rep, io, tail_dodge, tail_clicks, tail_aborted)
        self._d4_last_end = time.perf_counter()  # 供正常combo起手时记录交接间隔
        self.task.sleep_check()  # 被新声音打断时让排队的新闪避即时落地(和 combo_attack 同理)

    def _log_d4_outside_report(self, rep, io, tail_dodge, tail_clicks, tail_aborted):
        """续打执行报告: 各阶段标称/实际耗时/点击数/中止点。用于区分"程序没打完(有中止原因)"、
        "时序被拖长(实际耗时远超标称=系统调度/卡顿, 游戏内连段窗口错过)"、
        "程序完整但游戏没吃(报告全正常, 画面却没出第二个4a → 游戏侧丢输入/延迟)"。"""
        def seg(name, r):
            nominal, actual, clicks, aborted = r
            s = f"{name}{nominal:.0f}/{actual:.0f}ms {clicks}点"
            return s + ("(中止)" if aborted else "")

        def jump_seg(r):
            nominal, actual, executed = r
            return f"跳A{nominal:.0f}/{actual:.0f}ms" if executed else "跳A×"

        if rep is None:
            self.logger.info("双4a续打报告: 执行器未返回(异常提前退出)")
            return
        parts = [seg("前段", rep["front"]), jump_seg(rep["jump"]), seg("后段", rep["back"])]
        if tail_dodge is not None:
            parts.append(f"尾闪{tail_dodge}")
            parts.append(f"尾段{tail_clicks}点" + ("(中止)" if tail_aborted else ""))
        else:
            parts.append("尾闪×")
        reason = io.abort_reason or "无"
        self.logger.info(f"双4a续打报告: {' | '.join(parts)} | 中止原因={reason}")

    def on_dodge_counter(self):
        """触发闪避后按"安魂曲配置"的闪避反击方式走对应流程(与测试同一份配置):
        - 闪双4a: 前段平A的前~1秒在此打(填满声音窗口、立即反击), 剩余交 do_perform 无缝续打
          (见 _dodge_double_4a_inside / _run_double_4a_outside, 后段像普通combo可被新声音打断);
        - 方案一(默认): 强制平A打反击(0.1间隔) → 主动闪避取消后摇 → 记时刻, combo起手前等后摇。
        由 task.after_dodge_executed 在闪避键按下后(主线程内)同步调用。"""
        task = self._jump_task()
        style = task.config.get(task.CONF_DODGE_STYLE, task.STYLE_CURRENT) if task is not None else None
        if task is not None and style == task.STYLE_SCHEME_B:
            self._dodge_double_4a_inside(task)
            return
        duration = self._dodge_counter_duration()
        if duration <= 0:
            return
        self.logger.info(f"安魂曲闪避反击: 强制平A {duration:.2f}s → 主动闪避 → combo")
        start = time.time()
        while time.time() - start < duration:
            self.click()
            time.sleep(self.DODGE_COUNTER_INTERVAL)
        self._active_dodge()               # 主动闪避, 取消反击后摇
        self._dodge_counter_at = time.time()  # combo 起手前从这里算"闪避后到首平A"的等待

    def _wait_dodge_counter_recovery(self):
        """combo 起手前: 若紧接在闪避反击之后(在后摇窗口内), 等后摇走完再落第一下, 否则 combo 顺序乱。
        raw sleep 不插帧, 保 combo 起手时机。消费掉标记, 只对紧接反击的这一次 combo 生效。
        切人/技能/大招不走这里→立即执行取消后摇。"""
        if self._dodge_counter_at <= 0:
            return
        remaining = self._dodge_counter_combo_wait() - (time.time() - self._dodge_counter_at)
        self._dodge_counter_at = 0.0
        if remaining > 0:
            self.logger.info(f"combo 起手前等闪避反击后摇 {remaining:.2f}s")
            time.sleep(remaining)

    def idle_normal_attack(self, duration=None):
        """主C站场输出: 用一轮 4A跳A combo 替代原连点(原 2.5s)。放完一轮即返回、交战斗循环
        重新决策(下一圈再来一轮); 一轮内部可被闪避/切人打断。duration 参数忽略(一轮为准)。

        技能快就绪(剩余CD < 一轮combo时长)时不开整轮 combo: 一轮会把 do_perform 焊死 ~2.1s、
        期间技能就绪也不复检, 打完常和辅助资源撞一起→先切辅助把就绪技能晾着(浪费)。改用短平A
        填充让 do_perform 尽快复检、技能一好立刻放; 技能还远时才打完整 combo(输出不亏)。"""
        if self.should_yield_to_support():
            self.logger.info("support ready before requiem combo idle")
            return
        skill_cd = self.task.get_cd("skill", self.index)
        if 0 < skill_cd < self.IDLE_NEAR_SKILL_CD:
            self.logger.info(f"requiem skill 快就绪({skill_cd:.1f}s<1s), 0.1间隔平A盯就绪, 不开整轮combo")
            self.continues_normal_attack(skill_cd, interval=self.IDLE_NEAR_SKILL_INTERVAL)
            return
        self.combo_attack()

    def free_skill_followup_attack(self):
        """免费技能后的后续输出: 大招好了先开、辅助有资源就让位, 否则打一轮 combo。"""
        if self.ultimate_available():
            if self.click_ultimate():
                return
        if self.should_yield_to_support(include_probe=False):
            self.logger.info("support confirmed resource during requiem follow-up attack")
            return
        self.combo_attack()

    def _free_skill_break_a5(self):
        """免费技能放出后, 用闪避打断那又慢又低伤的第五下平A(a5), 省掉它直接接后续输出。
        实测只有闪避能打断 a5, 跳A(空格+左键)打不断, 故这里按一下游戏闪避键(lshift)。
        delay: 免费技能→闪避 的等待(核心); hold: 闪避键按住; wait: 闪避后到后续的间隔。全读"安魂曲配置"可实时调。
        hold<=0 视为关闭(不打断)。与测试脚手架(_run_free_skill_combo_test)同一份配置。"""
        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
        task = self._jump_task()
        delay = self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_FREE_BREAK_DELAY, self.FREE_BREAK_DELAY_MS, task=task)
        hold = self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_FREE_BREAK_JUMP_HOLD, self.FREE_BREAK_JUMP_HOLD_MS, task=task)
        wait = self._read_jump_task_conf(
            RequiemCombatConfigTask.CONF_FREE_BREAK_WAIT, self.FREE_BREAK_WAIT_MS, task=task)
        if hold <= 0:
            return  # 关: 不打断, 沿用免费技能后的默认后续(会顺出 a5)
        io = _RequiemCombatIO(self)  # 普通 io: 就一下闪避, 不需中途复查
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            if delay > 0:
                io.sleep_ms(delay)
            self.task.send_key_down(self.DODGE_KEY)   # 闪避打断 a5(实测只有闪避能打断, 跳A打不断)
            io.sleep_ms(hold)
            self.task.send_key_up(self.DODGE_KEY)
            if wait > 0:
                io.sleep_ms(wait)
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
        self.logger.info(f"免费技能后闪避打断a5: 等{delay:.0f}→闪避{hold:.0f}→等{wait:.0f}ms")

    def _mark_real_skill_overlap(self, reason):
        """真技能确认进CD后: 安排 overlap 下场 + 当场锚16s CD。
        不锚的话overlap切走后锚点停在放招前的"就绪", 切回来 cd-truth 误报"切早"(纯显示噪声)。"""
        self.skill_off_field_until = time.time() + self.SKILL_OFF_FIELD_DURATION
        self.task.note_skill_on_cd(self.index, cd=self.REAL_SKILL_CD)
        self.logger.info(f"requiem REAL skill {reason}, off-field overlap switch")

    def _real_skill_in_long_cd(self):
        """真技能按键后是否真进了"长CD"(= 真放成功了)。**只信这帧 OCR 真读到的 CD 数字**
        (skill_ocr_raw), 不经锚点推算、不看就绪图标——和统一规则一致: 读到数字才是真进CD。
        CD 数字有约 1s 滞后, 故在 REAL_SKILL_LANDED_CONFIRM_WINDOW 内轮询(每帧刷新 + 平A):
        一读到 >=REAL_SKILL_LANDED_MIN_CD 立即 True; 窗口内只读到就绪(无数字)/短CD → False
        (没放成/被打断)。"""
        deadline = time.time() + self.REAL_SKILL_LANDED_CONFIRM_WINDOW
        while True:
            raw = self.task.skill_ocr_raw(self.index)
            if raw is not None and raw >= self.REAL_SKILL_LANDED_MIN_CD:
                return True
            if time.time() >= deadline:
                return False
            self.normal_attack()
            self.sleep(self.REAL_SKILL_LANDED_POLL_INTERVAL)
            self.task.next_frame()

    def _try_land_real_skill(self):
        """放一次真技能并确认是否真进了**长CD**(= 放成功)。是→安排 overlap, 返回 True。
        还就绪(没按出去)/进短CD(被闪避打断的假成功)→ 返回 False, 交给 settle 补放/校准。"""
        if not self.click_skill():  # 上游click_skill改返回bool(原三元组)
            return False
        if self._skill_still_available_after_input_mode_delay():
            return False  # 还就绪 = 没按出去
        if not self._real_skill_in_long_cd():
            return False  # 进的是短CD = 被打断, 不算放成功
        self._mark_real_skill_overlap("cast")
        return True

    def cast_real_skill(self):
        """真技能分支(伤害大头): 先起手平A进交战再放真技能。放招那一下若紧接着触发闪避,
        可能被打断——和辅助走同一套统一结算 settle_skill_after_cast: 没按出去就补放(真技能
        值得久等, 上限 REAL_SKILL_RETRY_MAX_DURATION)、进了CD就读真实CD校准长短。结算完只有
        确认进了**长CD**(真放成功)才 overlap 下场; 短CD(被打断)/没放出则不切, 下轮重试。"""
        # 先平A出手进入交战, 再放真技能, 否则开战瞬间直接放会打空(技能消失)。
        attempt_at = time.time()
        engage = self.engage_attack_duration()
        if engage > 0:
            self.engage_before_skill(engage)
        if self._try_land_real_skill():
            return  # 一次就放进长CD(常见路径)→ 已 overlap
        # 没立即放成(被闪避打断/没按出去): 统一 settle 补放到放出 / 进CD校准真实长短。
        self.settle_skill_after_cast(
            attempt_at, self.REAL_SKILL_CD, max_duration=self.REAL_SKILL_RETRY_MAX_DURATION
        )
        if self._real_skill_in_long_cd():
            self._mark_real_skill_overlap("settled")
        else:
            self.logger.info("requiem REAL skill 未放进长CD(被打断/没放出), 不切, 下轮重试")

    def _skills_disabled_for_test(self, task=None):
        """读"安魂曲配置"的"禁用技能大招(测试)"开关: 开=只站场打 combo, 方便单独测手感/闪避。"""
        if task is None:
            task = self._jump_task()
        if task is None:
            return False
        try:
            return bool(task.config.get(task.CONF_DISABLE_SKILLS, False))
        except Exception:
            return False

    def do_perform(self):
        # 双4a"窗口外"续打: 闪避那 1 秒窗口里已在 execute_dodge 打了前段前半, 这里无缝接剩余部分
        # (前段剩余→跳A→后段→尾段闪避→补平A)。放在最顶上、跳过技能OCR, 免得在双4a中间插延迟打乱节奏。
        if getattr(self, "_pending_double_4a", None) is not None:
            self._run_double_4a_outside()
            return

        self.wait_intro()

        if self._skills_disabled_for_test():
            # 测试开关: 跳过技能/大招, 直接站场 combo(仍保留让位辅助的正常逻辑)。
            if self.should_yield_to_support():
                self.continues_normal_attack(0.2)
                return
            self.idle_normal_attack()
            return

        # 目标存活门: 开大/放技能前刷新一帧确认还在战斗, 别对着尸体开大或放真技能(白扔长CD)。
        # 已确认脱战则抛 NotInCombat 收手。和 combo 中途 _check_combat_alive 同一判定(带去抖不误停)。
        self._check_combat_alive()

        used_ultimate = self.click_ultimate(wait_if_no_cd=self.PRE_SKILL_ULTIMATE_WAIT)  # 上游参数改名(原wait_if_cd_ready)

        if self.skill_available():
            # 真/免费只看技能图标(is_real_skill_now);识别不到按真技能处理。
            if self.is_real_skill_now():
                # 真技能是伤害大头: 放进去(进CD)才 overlap; 被打断会留场重试到放出。
                self.cast_real_skill()
                return
            else:
                if self.click_skill(time_out=1.0):  # 上游click_skill改返回bool(原三元组)
                    # 免费技能:留场接平A,不触发下场。
                    self.logger.info("requiem FREE skill cast, staying on field")
                    self._free_skill_break_a5()  # 跳A打断拖沓低伤的第五下平A(a5), 不打那下
                    self.free_skill_followup_attack()
                    return

        if used_ultimate:
            return

        if self.should_yield_to_support():
            self.logger.info("support resource ready after requiem action check, yielding")
            self.continues_normal_attack(0.2)
            return

        self.idle_normal_attack()

    def reset_state(self):
        super().reset_state()
        self.skill_off_field_until = 0.0
        self._dodge_counter_at = 0.0
        self._pending_double_4a = None
        self._d4_front_left_ms = 0.0
        self._d4_seam_t = 0.0
        self._d4_last_end = 0.0
