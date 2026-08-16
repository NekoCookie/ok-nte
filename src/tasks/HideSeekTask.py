from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.lw.hide_seek_ext import HideSeekTaskMixin  # [lw]
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class HideSeekTask(HideSeekTaskMixin, NTEOneTimeTask, BaseNTETask):  # [lw]
    """徊影憧憧活动挂机任务, 自动点击开始匹配循环对局。  # [lw]"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动捉迷藏"
        self.description = "徊影憧憧活动自动挂机: 自动点击开始匹配, 对局结束自动开始下一局"
        self.icon = FluentIcon.SYNC
        self.group_name = "都市闲趣"
        self.group_icon = FluentIcon.GAME
        self.add_rounds_config(default=0)

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            raise
        except Exception as exc:
            self.screenshot("hide_seek_unexpected_exception")
            self.log_error("HideSeekTask error", exc)
            raise

    def do_run(self):
        total = self.configured_rounds(default=0)
        count = 0
        start_score = None
        while self.should_run_round(count + 1, total):
            count += 1
            round_text = self.rounds_info_text(count, total)
            self.info_set("轮次", round_text)
            self.log_info(f"开始第 {round_text} 局捉迷藏")
            button = self.wait_for_start_button(time_out=60)
            if button is None:
                self.log_error("未识别到开始匹配按钮, 任务结束")
                break
            score = self.read_match_score()
            if score is not None:
                current, score_total = score
                self.info_set("当前积分", f"{current}/{score_total}")
                if start_score is None:
                    start_score = current
                    self.info_set("起始积分", current)
                    self.log_info(f"启动时初始积分: {current}/{score_total}")
                elif current > start_score:
                    self.info_set("自动获取积分", current - start_score)
                    self.log_info(
                        f"当前积分 {current}/{score_total}, 自动累计获取 {current - start_score}"
                    )
            else:
                self.log_warning("本轮积分识别失败, 未更新积分信息")
            self.operate_click(button, action_name="hide_seek_start_match", interval=1)
            self.wait_enter_match()
            self.wait_round_end()
            self.log_info(f"第 {round_text} 局挂机结束")
        self.log_info(f"自动捉迷藏结束, 共完成 {count} 局", notify=True)