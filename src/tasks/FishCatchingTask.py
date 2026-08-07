from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.lw.fish_catch_ext import FishCatchingTaskMixin  # [lw]
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class FishCatchingTask(FishCatchingTaskMixin, NTEOneTimeTask, BaseNTETask):  # [lw]
    """自动捕鱼小游戏任务, 与自动钓鱼任务独立。  # [lw]"""

    CONF_TIMEOUT_SECONDS = "捕鱼单轮超时"
    CONF_CLICK_INTERVAL = "捕鱼点击间隔"
    DEFAULT_ROUNDS = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动捕鱼"
        self.description = "自动点击捕鱼场景中的彩色鱼"
        self.icon = FluentIcon.SYNC
        self.group_name = "都市闲趣"
        self.group_icon = FluentIcon.GAME
        self.add_rounds_config(default=self.DEFAULT_ROUNDS)
        self.default_config.update(
            {
                self.CONF_TIMEOUT_SECONDS: self.FISH_ROUND_TIMEOUT,
                self.CONF_CLICK_INTERVAL: self.FISH_CLICK_INTERVAL,
            }
        )
        self.config_description.update(
            {
                self.CONF_TIMEOUT_SECONDS: "单轮捕鱼最长运行时间, 超时后结束本轮",
                self.CONF_CLICK_INTERVAL: "捕鱼目标之间的点击间隔, 最小 0.05 秒",
            }
        )

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            raise
        except Exception as exc:
            self.screenshot("fish_catching_unexpected_exception")
            self.log_error("FishCatchingTask error", exc)
            raise

    def do_run(self):
        total = self.configured_rounds(default=self.DEFAULT_ROUNDS)
        count = 0
        while self.should_run_round(count + 1, total):
            count += 1
            self.log_info(f"开始第 {self.rounds_info_text(count, total)} 轮捕鱼")
            prepare_ready = self.ensure_catch_prepare()
            if prepare_ready:
                self.click_catch_start()
            if not self.run_fish_catch_round(self.config.get(self.CONF_TIMEOUT_SECONDS)):
                self.log_error("点击开始捕鱼后未进入捕鱼场景, 任务结束")
                break
            if self.should_run_round(count + 1, total):
                ready = self.wait_until(
                    self.find_catch_start_button,
                    time_out=10,
                    settle_time=0.5,
                    raise_if_not_found=False,
                )
                if not ready:
                    self.log_warning("捕鱼结束后未回到开始界面, 停止任务")
                    break
        self.log_info(f"自动捕鱼结束, 共完成 {count} 轮", notify=True)
