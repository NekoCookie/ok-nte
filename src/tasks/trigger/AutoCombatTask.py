from ok import Logger, TriggerTask
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    CONF_USE_ULT = "使用终结技"
    CONF_AUTO_TARGET = "自动目标"
    CONF_INTRO_MOTION_DURATION = "通用环合普攻时长(s)"
    CONF_COMBAT_START_PRIORITY = "启用开战优先级"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": True}
        self.trigger_interval = 0.1
        self.name = "自动战斗"
        self.description = "受《异环》UI的特殊性影响, 部分场景下存在识别稳定性波动"
        self.icon = FluentIcon.CALORIES
        self.last_is_click = False
        self.default_config.update(
            {
                self.CONF_AUTO_TARGET: True,
                self.CONF_USE_ULT: True,
                self.CONF_INTRO_MOTION_DURATION: 1.5,
                self.CONF_COMBAT_START_PRIORITY: True,
            }
        )
        self.config_description = {
            self.CONF_AUTO_TARGET: "关闭时仅在中键选中敌人且画面识别到关键特征时开启战斗",
            self.CONF_INTRO_MOTION_DURATION: (
                "环合切人后的通用普攻时长, 默认1.5s且每0.1s普攻一次; "
                "开启实战合轴的残虹主C改用自身静默等待"
            ),
            self.CONF_COMBAT_START_PRIORITY: "关闭时不按角色执行开战首切",
        }

    def switch_to_combat_start_char(self):
        if not self.config.get(self.CONF_COMBAT_START_PRIORITY, True):
            logger.info("combat start priority disabled by config")
            return
        super().switch_to_combat_start_char()

    def run(self):
        """运行合并了 RU 战斗行为与 LW 队伍热重载的唯一主循环。"""
        return self.lw_combat_run()  # [lw] 单一路径接入 src/lw/combat_ext.py
