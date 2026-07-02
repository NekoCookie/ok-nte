import ctypes
import time

import cv2
import numpy as np
import win32con

from src.char.MainDps import MainDps
from src.combat import requiem_combo
from src.Labels import Labels
from src.sound_trigger.SoundCombatContext import SoundCombatContext


class _RequiemCombatIO:
    """实战里跑 4A跳A combo 的 io 适配器: 走框架后台 PostMessage(不动真实鼠键、游戏可不在前台)。
    should_continue 用廉价标志位判断"闪避待执行/已不是当前角色", 命中即中止本轮 combo, 把控制权
    交回战斗循环——待执行的闪避会在随后的 sleep_check 落地。intra-combo 用 raw sleep 保节奏。"""

    def __init__(self, char):
        self._char = char
        self._itx = char.task.executor.interaction
        try:
            cx = round(self._itx.capture.width * 0.5)
            cy = round(self._itx.capture.height * 0.5)
            self._pos = self._itx.update_mouse_pos(cx, cy)
        except Exception:
            self._pos = self._itx.update_mouse_pos(-1, -1)

    def should_continue(self):
        return self._char.is_current_char and not SoundCombatContext.should_interrupt_combat()

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
    # 闪避反击: 触发闪避后强制平A的默认秒数(配置读不到时用)与点击间隔。
    # 实际秒数在 4A 测试任务(RequiemJumpAttackTestTask)里可配, 便于实时调。
    DODGE_COUNTER_ATTACK = 0.3
    DODGE_COUNTER_INTERVAL = 0.1
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

    _skill_real_template = None
    _skill_free_template = None
    _skill_templates_loaded = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill_off_field_until = 0.0
        self._dodge_counter_at = 0.0  # 上次闪避反击出手时刻(供 combo 起手前等后摇)

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
        """真技能前的起手平A时长,优先读自动战斗任务的配置,便于实时调。"""
        try:
            return max(0.0, float(self.task.config.get(self.CONF_ENGAGE_ATTACK, self.SKILL_ENGAGE_ATTACK)))
        except (AttributeError, TypeError, ValueError):
            return self.SKILL_ENGAGE_ATTACK

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

    def combo_attack(self):
        """主C的普通攻击 = 跑一轮 4A跳A combo(时序见 requiem_combo, 与跳A宏方案一同源)。
        走后台 PostMessage; 提 1ms 定时精度 + raw sleep 保节奏(self.sleep 会插帧截图, 打乱 combo);
        每一下之前查 should_continue, 闪避待执行/已切走即中止, 交回战斗循环让闪避随后落地。"""
        self.check_combat()  # 战斗已结束/切队则抛出, 不空打一轮
        self._wait_dodge_counter_recovery()  # 若紧接闪避反击, 先等其后摇再起 combo(顺序不乱)
        io = _RequiemCombatIO(self)
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            requiem_combo.run_scheme_a(io)
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)

    def _read_jump_task_conf(self, key, default):
        """读 4A 测试任务(RequiemJumpAttackTestTask)的某个数值配置(可实时调), 读不到用默认。"""
        try:
            from src.tasks.trigger.RequiemJumpAttackTestTask import RequiemJumpAttackTestTask

            task = self.task.get_task_by_class(RequiemJumpAttackTestTask)
            if task is not None:
                return max(0.0, float(task.config.get(key, default)))
        except Exception as e:
            self.logger.debug(f"read jump task config {key} failed: {e}")
        return default

    def _dodge_counter_duration(self):
        from src.tasks.trigger.RequiemJumpAttackTestTask import RequiemJumpAttackTestTask
        return self._read_jump_task_conf(
            RequiemJumpAttackTestTask.CONF_DODGE_COUNTER, self.DODGE_COUNTER_ATTACK)

    def _dodge_counter_combo_wait(self):
        from src.tasks.trigger.RequiemJumpAttackTestTask import RequiemJumpAttackTestTask
        return self._read_jump_task_conf(
            RequiemJumpAttackTestTask.CONF_DODGE_COMBO_WAIT, self.DODGE_COUNTER_COMBO_WAIT)

    def on_dodge_counter(self):
        """触发闪避后强制平A一小段(0.1间隔), 保证安魂曲高伤闪避反击一定打出。
        由 task.after_dodge_executed 在闪避键按下后(主线程内)同步调用。**刻意用 raw time.sleep +
        直接点击、不走 self.sleep/sleep_check**: 这段期间不可被技能/大招/切人/新的sleep_check打断,
        这正是"保证反击"的目的。时长可在 4A 测试任务里配, 0=关闭。
        记下反击出手时刻: 若紧接着起 combo, combo 会先等这一下的后摇(见 _wait_dodge_counter_recovery);
        接切人/技能/大招则不等(它们能取消后摇)。"""
        duration = self._dodge_counter_duration()
        if duration <= 0:
            return
        self.logger.info(f"安魂曲闪避反击: 强制平A {duration:.2f}s(不可打断)")
        start = time.time()
        while time.time() - start < duration:
            self.click()
            time.sleep(self.DODGE_COUNTER_INTERVAL)
        self._dodge_counter_at = time.time()

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
        if not self.click_skill()[0]:
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

    def do_perform(self):
        self.wait_intro()

        used_ultimate = self.click_ultimate(wait_if_cd_ready=self.PRE_SKILL_ULTIMATE_WAIT)

        if self.skill_available():
            # 真/免费只看技能图标(is_real_skill_now);识别不到按真技能处理。
            if self.is_real_skill_now():
                # 真技能是伤害大头: 放进去(进CD)才 overlap; 被打断会留场重试到放出。
                self.cast_real_skill()
                return
            else:
                if self.click_skill(time_out=1.0)[0]:
                    # 免费技能:留场接平A,不触发下场。
                    self.logger.info("requiem FREE skill cast, staying on field")
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
