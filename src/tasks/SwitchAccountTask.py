# [lw] 用户自有任务: 自动切换账号(UI流, 全程后台鼠标 operate_click)。
# 依赖 HOTTA SDK 登录器已"记住"多个账号(免密点选), 流程:
# 游戏内 back_to_login → 登录界面点"退出账号" → 确认 → HOTTA面板展开账号列表
# → OCR认UID点目标账号 → 登录 → ensure_main 点"进入游戏"回世界。
import re

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask

# UID为8~10位纯数字整行; 手机号行含掩码星号(或吞星号后仅7位), 均不会误匹配
UID_RE = re.compile(r"^\d{8,10}$")
# 全匹配"登录"两字, 避免点到下方的"使用其他方式登录"
LOGIN_BTN_RE = re.compile(r"^登\s*录$")


class SwitchAccountTask(NTEOneTimeTask, BaseNTETask):
    CONF_TARGET_UID = "目标账号UID"

    # 登录界面右侧竖排图标第4个: "退出账号"(设置/公告/客服之下的门形图标)
    LOGOUT_ICON = (0.9715, 0.3156)
    # 退出账号确认弹窗的按钮行, 罩住取消+确认, find_confirm 会OCR认字挑"确认"
    CONFIRM_RANGE = (0.28, 0.60, 0.72, 0.72)
    # HOTTA SDK 账号面板整体区域(OCR用, 避开四周的FPS/版本号/备案号文字)
    PANEL_RANGE = (0.35, 0.19, 0.65, 0.80)
    # 折叠态当前账号行右端的下拉箭头。注意: 展开态同位置是"删除账号"垃圾桶,
    # 必须确认面板处于折叠态(仅1个UID可见)才允许点这里
    DROPDOWN_ARROW = (0.5975, 0.391)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "切换账号"
        self.description = "退出当前账号, 从HOTTA已记住的账号列表免密切换到另一个账号并进入游戏"
        self.icon = FluentIcon.PEOPLE
        self.default_config.update({self.CONF_TARGET_UID: ""})
        self.config_description.update(
            {
                self.CONF_TARGET_UID: "登录面板账号条目下方的数字ID; 留空=自动切到列表中另一个账号",
            }
        )

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("切换账号失败", e)

    def do_run(self):
        target = str(self.config.get(self.CONF_TARGET_UID) or "").strip()
        self.ensure_at_login_screen()
        self.open_account_panel()
        chosen = self.select_account(target)
        self.login_and_enter(chosen)

    # ---- 步骤 ----

    def ensure_at_login_screen(self):
        if self.at_login_screen():
            return
        self.log_info("当前在游戏内, 先退出到登录界面")
        self.back_to_login()
        if not self.wait_until(self.at_login_screen, time_out=60, raise_if_not_found=False):
            raise RuntimeError("未能回到登录界面")

    def open_account_panel(self):
        self.operate_click(*self.LOGOUT_ICON, after_sleep=1)
        self.wait_click_confirm(range=self.CONFIRM_RANGE, time_out=10)
        if not self.wait_until(self.read_account_uids, time_out=20, raise_if_not_found=False):
            raise RuntimeError("退出账号后 HOTTA 账号面板未出现")

    def select_account(self, target):
        uids = self.read_account_uids()
        current = uids[0].name if len(uids) == 1 else None
        if target and current == target:
            self.log_info(f"面板当前已选中目标账号 {target}")
            return target
        if current is not None:
            # 折叠态: 点箭头展开账号列表
            self.operate_click(*self.DROPDOWN_ARROW, after_sleep=1)
        row = self.wait_until(
            lambda: self.find_target_row(target, current), time_out=10, raise_if_not_found=False
        )
        if not row:
            raise RuntimeError(f"账号列表中没找到目标账号: {target or '<另一个账号>'}")
        chosen = row.name
        self.log_info(f"点选账号 {chosen}")
        self.operate_click(row, after_sleep=1)
        if not self.wait_until(
            lambda: self.collapsed_current() == chosen, time_out=8, raise_if_not_found=False
        ):
            raise RuntimeError(f"点选账号 {chosen} 后面板未收起到该账号")
        return chosen

    def login_and_enter(self, chosen):
        login_btn = self.wait_until(self.find_login_button, time_out=8, raise_if_not_found=False)
        if not login_btn:
            raise RuntimeError("HOTTA 面板上没找到登录按钮")
        self.operate_click(login_btn, after_sleep=2)
        # SDK登录完成后面板消失, 回到"进入游戏"界面
        if not self.wait_until(
            lambda: self.at_login_screen() and not self.read_account_uids(),
            time_out=60,
            raise_if_not_found=False,
        ):
            raise RuntimeError("点登录后未回到进入游戏界面")
        self.scene.set_logged_in(False)
        self.log_info(f"账号已切到 {chosen}, 开始进入游戏")
        self.ensure_main(time_out=120)
        self.log_info(f"切换账号完成: {chosen}", notify=True)

    # ---- 识别 ----

    def at_login_screen(self):
        # login_setting=登录界面右上角齿轮; HOTTA面板开着时它也可见,
        # 判断"纯登录界面"需另加 read_account_uids 为空
        return bool(self.find_one(Labels.login_setting))

    def read_account_uids(self):
        return self.ocr(box=self.box_of_screen(*self.PANEL_RANGE, name="hotta_panel"), match=UID_RE) or []

    def collapsed_current(self):
        uids = self.read_account_uids()
        return uids[0].name if len(uids) == 1 else None

    def find_target_row(self, target, current):
        uids = self.read_account_uids()
        if len(uids) < 2:
            return None  # 列表还没展开
        return self.pick_target(uids, target, current)

    @staticmethod
    def pick_target(uid_boxes, target, current):
        """从展开的账号列表挑目标行: 指定UID精确匹配; 未指定则取第一个非当前账号的。"""
        for box in uid_boxes:
            if target:
                if box.name == target:
                    return box
            elif box.name != current:
                return box
        return None

    def find_login_button(self):
        results = self.ocr(
            box=self.box_of_screen(*self.PANEL_RANGE, name="hotta_panel"), match=LOGIN_BTN_RE
        )
        return results[0] if results else None
