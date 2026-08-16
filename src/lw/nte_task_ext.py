# [lw] BaseNTETask 的用户扩展:
# - find_confirm 用 OCR 认字挑真确认键, 防游戏更新调换确认/取消位置或配色
#   (接线: BaseNTETask.find_confirm 一行委托到这里)
# - lw_daily_account_cycle: DailyRoutineTask 跑完自动换号再跑一轮的钩子
#   (接线: DailyRoutineTask.run 一行调用)
import re
from typing import TYPE_CHECKING

from ok import Box, Logger

from src.Labels import Labels

if TYPE_CHECKING:
    from src.tasks.BaseNTETask import BaseNTETask

    _TaskProxy = BaseNTETask
else:

    class _TaskProxy:
        pass


logger = Logger.get_logger(__name__)

confirm_text_re = re.compile("确认|确定")
cancel_text_re = re.compile("取消")

# 取自 confirm_btn_2 模板(assets/images/0.png)的粉色实测范围
confirm_pink_color = {
    "r": (233, 255),
    "g": (74, 96),
    "b": (138, 160),
}


class NTETaskExtMixin(_TaskProxy):
    def lw_confirm_ready_color(self, button, default_color):
        """确认按钮"完全显示"该等的颜色: 白色款等白(default), 粉色款(confirm_btn_2)等粉。
        游戏更新后按钮有两种款式, 等错颜色会一直等到超时才点。"""
        if "confirm_btn_2" in str(button.name):
            return confirm_pink_color
        return default_color

    def lw_find_confirm(self, box=None, threshold=0.7, mask_function=None):
        if not isinstance(box, Box):
            box = self.main_viewport
        candidates = []
        # 确认/取消可能是同一款式(如全白), 每个模板要收集多个匹配而非单个最佳,
        # 否则真确认键根本进不了候选
        for label in (Labels.confirm_btn_1, Labels.confirm_btn_2):
            boxes = self.find_feature(
                label,
                box=box,
                threshold=threshold,
                mask_function=mask_function,
            )
            if boxes:
                candidates.extend(boxes)
        if not candidates:
            return None
        return self._pick_confirm_button(candidates)

    def _pick_confirm_button(self, candidates):
        """挑出真正的确认键。

        按钮模板只认样式不认文字, 游戏更新可能调换确认/取消的位置或配色,
        点击前先 OCR 按钮文字: 优先点"确认/确定", 明确是"取消"的不点,
        识别不出文字的按模板匹配度兜底。
        """
        unknown = []
        # 无字模板可能误匹配复选框等杂项, 只保留置信度最高的几个做OCR
        candidates = sorted(candidates, key=lambda b: b.confidence, reverse=True)[:4]
        for btn in candidates:
            text = self._read_confirm_btn_text(btn)
            if confirm_text_re.search(text):
                return btn
            if cancel_text_re.search(text):
                logger.info(f"find_confirm skip cancel button {btn} text={text}")
                continue
            unknown.append(btn)
        if not unknown:
            logger.warning("find_confirm all candidates look like cancel")
            return None
        return unknown[0]

    def lw_daily_account_cycle(self):
        """DailyRoutineTask 收尾钩子: "切换账号"任务开了随日常轮换开关时, 自动换号再跑一轮日常。

        只在 DailyTask.run 的 do_run 正常结束后调用一次; 第二轮直接调 do_run,
        不再经过钩子, 天然不会无限循环。换号目标固定"另一个账号"(不读目标UID配置)。
        开了"切回原账号"开关时, 第二轮正常跑完后按第一次切号记下的原UID切回;
        第二轮异常则不切回(异常态下盲切可能更糟, 交给用户处理)。
        """
        # 局部 import: SwitchAccountTask → BaseNTETask → 本模块, 顶部引会循环
        from src.tasks.SwitchAccountTask import SwitchAccountTask, switch_account

        record_result = getattr(self, "lw_record_current_routine_result", None)

        def record_account_result(account_name, account_uid=None):
            if callable(record_result):
                record_result(account_name, account_uid)

        set_current_account = getattr(self, "lw_set_current_daily_account", None)

        def set_current_daily_account(account_uid):
            if callable(set_current_account):
                set_current_account(account_uid)

        switch = self.get_task_by_class(SwitchAccountTask)
        if not switch or not switch.config.get(SwitchAccountTask.CONF_CYCLE_WITH_DAILY):
            record_account_result("当前账号")
            return
        self.log_info("日常任务完成, 自动切换账号再跑一轮", notify=True)
        second_account_uid, first_account_uid = switch_account(self)
        set_current_daily_account(second_account_uid)
        record_account_result("账号 1", first_account_uid)
        self.do_run()
        record_account_result("账号 2", second_account_uid)
        if switch.config.get(SwitchAccountTask.CONF_SWITCH_BACK):
            # original 为 None(面板打开时已展开, 没读到折叠态原UID)时退化为"切到另一个"
            self.log_info(
                f"第二轮日常完成, 切回原账号 {first_account_uid or '<另一个账号>'}",
                notify=True,
            )
            selected_account_uid, _ = switch_account(self, first_account_uid or "")
            set_current_daily_account(selected_account_uid)

    def _read_confirm_btn_text(self, btn):
        # 模板只是按钮端头, 文字在旁边, 向左右各扩2倍宽; 越界box会被crop_image
        # 静默替换为整帧导致读到全屏文字, 必须先钳到帧内
        expand = btn.width * 2
        x = max(0, btn.x - expand)
        to_x = min(self.screen_width, btn.x + btn.width + expand)
        ocr_box = Box(x, btn.y, to_x - x, btn.height, name="confirm_btn_text")
        texts = self.ocr(box=ocr_box)
        if not texts:
            return ""
        nearest = min(texts, key=lambda t: t.center_distance(btn))
        return nearest.name or ""
