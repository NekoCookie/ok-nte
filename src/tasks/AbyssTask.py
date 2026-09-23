from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask
from src.lw.abyss_ext import AbyssAbort, AbyssTaskMixin  # [lw]
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class AbyssTask(AbyssTaskMixin, NTEOneTimeTask, BaseCombatTask):  # [lw]
    """轨外之境自动挑战, 从第一个未满星站点开始逐站推进。  # [lw]"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动深渊"
        self.description = "轨外之境: 从首个未满星站点开始自动挑战, 通关后找乘务员去下一站"
        self.icon = FluentIcon.FLAG
        self.configure_abyss()

    def run(self):
        super().run()
        try:
            self.abyss_run()
        except TaskDisabledException:
            pass
        except AbyssAbort as e:
            self.screenshot("abyss_abort")
            self.log_error(f"自动深渊停止: {e}", notify=True)
        except Exception as e:
            self.screenshot("abyss_unexpected_exception")
            self.log_error("AbyssTask Error", e)
