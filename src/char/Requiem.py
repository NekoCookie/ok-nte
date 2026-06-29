import time

import cv2
import numpy as np

from src.char.MainDps import MainDps
from src.Labels import Labels


class Requiem(MainDps):
    """Main DPS template with off-field skill overlap after skill cast."""

    SKILL_OFF_FIELD_DURATION = 3.0
    REAL_SKILL_CD = 16.0  # 真技能固定16s CD(从释放起算);免费技能不影响, 不锚。
    # 真技能(伤害大头)放招瞬间常被闪避打断、按键没进CD。被打断后继续平A(打出闪避反击)
    # 并反复重试放招的最长时间; 超时仍没放进就本轮放弃, 下轮再试。不死等。
    REAL_SKILL_RETRY_MAX_DURATION = 3.0
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

    def free_skill_followup_attack(self):
        start = time.time()
        while time.time() - start < self.FREE_SKILL_FOLLOWUP_ATTACK_DURATION:
            if self.ultimate_available():
                if self.click_ultimate():
                    return
            if self.should_yield_to_support(include_probe=False):
                self.logger.info("support confirmed resource during requiem follow-up attack")
                return
            self.normal_attack()
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)

    def _mark_real_skill_overlap(self, reason):
        """真技能确认进CD后: 安排 overlap 下场 + 当场锚16s CD。
        不锚的话overlap切走后锚点停在放招前的"就绪", 切回来 cd-truth 误报"切早"(纯显示噪声)。"""
        self.skill_off_field_until = time.time() + self.SKILL_OFF_FIELD_DURATION
        self.task.note_skill_on_cd(self.index, cd=self.REAL_SKILL_CD)
        self.logger.info(f"requiem REAL skill {reason}, off-field overlap switch")

    def _try_land_real_skill(self):
        """放一次真技能并确认是否真进CD。进了→安排 overlap 下场, 返回 True;
        按键被吞/被闪避打断没进CD→返回 False(调用方继续平A重试)。"""
        if not self.click_skill()[0]:
            return False
        if self._skill_still_available_after_input_mode_delay():
            return False
        self._mark_real_skill_overlap("cast")
        return True

    def cast_real_skill(self):
        """真技能分支: 先起手平A进交战再放真技能。真技能是伤害大头——若放招瞬间触发闪避被
        打断、按键没进CD, 不放弃: 继续平A把闪避反击打出来并反复重试, 直到真技能真的进CD再
        overlap 下场。不死等, 上限 REAL_SKILL_RETRY_MAX_DURATION; 超时仍没放进就本轮放弃
        (不切人, 下轮 do_perform 重试)。"""
        # 先平A出手进入交战, 再放真技能, 否则开战瞬间直接放会打空(技能消失)。只起手一次,
        # 重试期间本就在平A, 已交战, 无需再起手。
        engage = self.engage_attack_duration()
        if engage > 0:
            self.engage_before_skill(engage)
        if self._try_land_real_skill():
            return
        deadline = time.time() + self.REAL_SKILL_RETRY_MAX_DURATION
        while time.time() < deadline:
            # 被打断没放进: 平A把闪避反击打出来, 再重试放招。
            self.normal_attack()
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)
            if not self.skill_available():
                # 技能已不在可用态 = 刚那次其实放进CD了, 直接安排 overlap。
                self._mark_real_skill_overlap("landed during retry")
                return
            if self._try_land_real_skill():
                return
        self.logger.info("requiem REAL skill 反复被打断超时, 本轮放弃(下轮重试)")

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
