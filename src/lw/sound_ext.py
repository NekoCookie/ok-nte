# [lw] SoundCombatContext 的用户扩展: 闪避时刻查询、待执行动作查询、闪避暂停开关。
# 接线: class SoundCombatContext(SoundContextExtMixin)。


class SoundContextExtMixin:
    _dodge_paused = False

    def last_dodge_time(self):
        """上次声音触发闪避的时刻(time.time()), 没触发过返回 0。
        闪避是我方主动触发(记了时刻), 所以"放完技能是否立刻闪避"可确定性判断, 不必靠图标猜。"""
        trigger = self._trigger
        return getattr(trigger, "_last_dodge_time", 0.0) if trigger else 0.0

    def has_pending_action(self):
        """是否有"新的声音闪避在排队待执行"。用于闪避反击(双4a)期间: 反击本身在处理"当前这次"
        闪避、combat_interrupt 尚为当前闪避而 set(不能拿它判断中止), 但一旦来了**新的**敌人攻击
        会入队 _pending_action —— 反击应立刻中止让位, 把主线程交回去执行那次救命闪避。"""
        with self._context_lock:
            return self._pending_action is not None

    @classmethod
    def set_dodge_paused(cls, paused):
        """暂停/恢复声音自动闪避。仅用于"安魂曲配置"的闪避反击测试: 跑一整轮期间暂停, 免得
        SoundTriggerTask 对真·敌人攻击的自动闪避插进测试的 combo 里、看不清完整一轮。实战不用。"""
        cls._dodge_paused = bool(paused)
