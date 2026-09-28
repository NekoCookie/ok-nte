from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.lw.ocr_click_ext import OcrClickTaskMixin  # [lw]
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class OcrClickTask(OcrClickTaskMixin, NTEOneTimeTask, BaseNTETask):  # [lw]
    """全屏OCR识别配置文字并按优先级点击, 独立于活动配置。  # [lw]"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "OCR识别点击"
        self.description = "全屏OCR识别配置的文字并按优先级循环点击, 手动停止或到时结束"
        self.icon = FluentIcon.SEARCH
        self.configure_ocr_click()

    def run(self):
        super().run()
        try:
            self.ocr_click_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.screenshot("ocr_click_unexpected_exception")
            self.log_error("OcrClickTask Error", e)
