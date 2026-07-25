from ok import TriggerTask
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask


class AutoCombatTask(BaseCombatTask, TriggerTask):
    CONF_USE_ULT = "使用终结技"
    CONF_AUTO_TARGET = "自动目标"

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
            }
        )
        self.config_description = {
            self.CONF_AUTO_TARGET: "关闭时仅在中键选中敌人且画面识别到 'Lv' 文字时开启战斗",
        }
        self.op_index = 0
        self.origin_func = {}

    def run(self):
        """运行合并了 RU 战斗行为与 LW 队伍热重载的唯一主循环。"""
        return self.lw_combat_run()  # [lw] 单一路径接入 src/lw/combat_ext.py
