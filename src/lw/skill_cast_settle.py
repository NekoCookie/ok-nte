"""[lw] 技能释放后因闪避打断而需要的收尾结算能力。"""

import time


class SkillCastSettleMixin:
    """仅供需要长 CD 技能补发/校准的 LW 角色模板使用。"""

    SKILL_SETTLE_MAX_DURATION = 0.5
    SKILL_SETTLE_INTERVAL = 0.1
    # OCR 读到小于该值的 CD 多为图标未稳定，不视为真正进入 CD。
    SKILL_SETTLE_MIN_ON_CD = 1.0

    def settle_skill_after_cast(self, cast_at, cooldown, max_duration=None):
        """放招后发生闪避时，确认技能已进 CD；未放出则在短窗口内补发。"""
        if not self.is_current_char:
            return False

        # 放招瞬间触发的闪避可能还在队列中，先落地再判断，避免紧接切人时漏检。
        self.task.flush_pending_dodge()
        if not (cast_at > 0 and self.task.last_dodge_time() >= cast_at):
            return False

        down_time = getattr(self, "SKILL_DOWN_TIME", 0.01)
        self.logger.info("放招后触发闪避, 留场结算技能(校准/补放)")
        duration = self.SKILL_SETTLE_MAX_DURATION if max_duration is None else max_duration
        deadline = time.time() + duration
        while time.time() < deadline:
            self.task.next_frame()
            # 只认本帧 OCR 原始 CD；推算 CD 会被刚写入的标称值污染。
            raw = self.task.skill_ocr_raw(self.index)
            if raw is not None and raw >= self.SKILL_SETTLE_MIN_ON_CD:
                self.logger.info(f"放招后结算: 技能已进CD, 校准为真实CD={raw:.1f}s")
                return True

            self.send_skill_key(down_time=down_time)
            self.task.note_skill_on_cd(self.index, cd=cooldown)
            self.normal_attack()
            self.sleep(self.SKILL_SETTLE_INTERVAL)

        self.task.note_skill_ready(self.index)
        self.logger.info("放招后结算: 超时仍就绪(没放出), 锚为就绪等下次")
        return False
