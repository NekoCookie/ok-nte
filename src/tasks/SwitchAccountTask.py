# [lw] 用户自有任务: 自动切换账号(UI流, 全程后台鼠标 operate_click)。
# 依赖 HOTTA SDK 登录器已"记住"多个账号(免密点选), 流程:
# 游戏内 back_to_login → 登录界面点"退出账号" → 确认 → HOTTA面板展开账号列表
# → OCR认UID点目标账号 → 登录 → ensure_main 点"进入游戏"回世界。
#
# 切号流程写成模块级函数(接收task参数): DailyTask 的"跑完自动换号再跑一轮"钩子
# (src/lw/nte_task_ext.py 的 lw_daily_account_cycle)在 DailyTask 自身实例上执行,
# 避免跨任务实例调用 sleep/operate 的运行态问题。
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

# 登录界面右侧竖排图标第4个: "退出账号"(设置/公告/客服之下的门形图标)
LOGOUT_ICON = (0.9715, 0.3156)
# 退出账号确认弹窗的按钮行, 罩住取消+确认, find_confirm 会OCR认字挑"确认"
CONFIRM_RANGE = (0.28, 0.60, 0.72, 0.72)
# HOTTA SDK 账号面板整体区域(OCR用, 避开四周的FPS/版本号/备案号文字)
PANEL_RANGE = (0.35, 0.19, 0.65, 0.80)
# 折叠态当前账号行右端的下拉箭头。注意: 展开态同位置是"删除账号"垃圾桶,
# 必须确认面板处于折叠态(仅1个UID可见)才允许点这里
DROPDOWN_ARROW = (0.5975, 0.391)


class SwitchAccountTask(NTEOneTimeTask, BaseNTETask):
    CONF_TARGET_UID = "目标账号UID"
    CONF_CYCLE_WITH_DAILY = "日常跑完自动换号再跑一轮"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "切换账号"
        self.description = "退出当前账号, 从HOTTA已记住的账号列表免密切换到另一个账号并进入游戏"
        self.icon = FluentIcon.PEOPLE
        # 与 DailyTask 同组, 显示在"日常任务"下方
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.default_config.update(
            {
                self.CONF_TARGET_UID: "",
                self.CONF_CYCLE_WITH_DAILY: False,
            }
        )
        self.config_description.update(
            {
                self.CONF_TARGET_UID: "登录面板账号条目下方的数字ID; 留空=自动切到列表中另一个账号",
                self.CONF_CYCLE_WITH_DAILY: "运行日常任务时, 跑完自动切到另一个账号再跑一轮日常(无需手动运行本任务)",
            }
        )

    def run(self):
        super().run()
        try:
            target = str(self.config.get(self.CONF_TARGET_UID) or "").strip()
            switch_account(self, target)
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("切换账号失败", e)


def switch_account(task, target=""):
    """在任意 BaseNTETask 实例上执行完整切号流程, 返回切到的UID。"""
    ensure_at_login_screen(task)
    open_account_panel(task)
    chosen = select_account(task, target)
    login_and_enter(task, chosen)
    return chosen


# ---- 步骤 ----


def ensure_at_login_screen(task):
    if not at_login_screen(task):
        task.log_info("当前在游戏内, 先退出到登录界面")
        task.back_to_login()
        if not task.wait_until(lambda: at_login_screen(task), time_out=60, raise_if_not_found=False):
            raise RuntimeError("未能回到登录界面")
    # 上游 wait_login 在登录界面点击前也会置前, HOTTA SDK 面板在后台窗口下行为不可靠
    if not task.is_foreground():
        task.bring_to_front()
        task.sleep(3)


def open_account_panel(task):
    if read_account_uids(task):
        task.log_info("HOTTA 账号面板已打开")
        return
    task.operate_click(*LOGOUT_ICON, after_sleep=1)
    task.wait_click_confirm(range=CONFIRM_RANGE, time_out=10)
    if not task.wait_until(lambda: read_account_uids(task), time_out=20, raise_if_not_found=False):
        dump_panel_diagnostics(task)
        raise RuntimeError("退出账号后 HOTTA 账号面板未出现(诊断截图与窗口列表已存日志)")


def select_account(task, target):
    uids = read_account_uids(task)
    current = uids[0].name if len(uids) == 1 else None
    if target and current == target:
        task.log_info(f"面板当前已选中目标账号 {target}")
        return target
    if current is not None:
        # 折叠态: 点箭头展开账号列表
        task.operate_click(*DROPDOWN_ARROW, after_sleep=1)
    row = task.wait_until(
        lambda: find_target_row(task, target, current), time_out=10, raise_if_not_found=False
    )
    if not row:
        raise RuntimeError(f"账号列表中没找到目标账号: {target or '<另一个账号>'}")
    chosen = row.name
    task.log_info(f"点选账号 {chosen}")
    task.operate_click(row, after_sleep=1)
    if not task.wait_until(
        lambda: collapsed_current(task) == chosen, time_out=8, raise_if_not_found=False
    ):
        raise RuntimeError(f"点选账号 {chosen} 后面板未收起到该账号")
    return chosen


def login_and_enter(task, chosen):
    login_btn = task.wait_until(lambda: find_login_button(task), time_out=8, raise_if_not_found=False)
    if not login_btn:
        raise RuntimeError("HOTTA 面板上没找到登录按钮")
    task.operate_click(login_btn, after_sleep=2)
    # SDK登录完成后面板消失, 回到"进入游戏"界面
    if not task.wait_until(
        lambda: at_login_screen(task) and not read_account_uids(task),
        time_out=60,
        raise_if_not_found=False,
    ):
        raise RuntimeError("点登录后未回到进入游戏界面")
    task.scene.set_logged_in(False)
    task.log_info(f"账号已切到 {chosen}, 开始进入游戏")
    task.ensure_main(time_out=120)
    task.log_info(f"切换账号完成: {chosen}", notify=True)


# ---- 识别 ----


def at_login_screen(task):
    # login_setting=登录界面右上角齿轮; HOTTA面板开着时它也可见,
    # 判断"纯登录界面"需另加 read_account_uids 为空
    return bool(task.find_one(Labels.login_setting))


def read_account_uids(task):
    return task.ocr(box=task.box_of_screen(*PANEL_RANGE, name="hotta_panel"), match=UID_RE) or []


def collapsed_current(task):
    uids = read_account_uids(task)
    return uids[0].name if len(uids) == 1 else None


def find_target_row(task, target, current):
    uids = read_account_uids(task)
    if len(uids) < 2:
        return None  # 列表还没展开
    return pick_target(uids, target, current)


def pick_target(uid_boxes, target, current):
    """从展开的账号列表挑目标行: 指定UID精确匹配; 未指定则取第一个非当前账号的。"""
    for box in uid_boxes:
        if target:
            if box.name == target:
                return box
        elif box.name != current:
            return box
    return None


def find_login_button(task):
    results = task.ocr(box=task.box_of_screen(*PANEL_RANGE, name="hotta_panel"), match=LOGIN_BTN_RE)
    return results[0] if results else None


# ---- 诊断 ----


def dump_panel_diagnostics(task):
    """面板等不到时: 存一张当前捕获帧 + 枚举游戏进程的全部顶层窗口。
    用于区分"面板没弹出"和"面板是独立窗口、不在游戏窗口捕获画面里"。"""
    try:
        task.screenshot("switch_account_no_panel")
    except Exception as e:
        task.log_info(f"诊断截图失败: {e}")
    try:
        import psutil
        import win32gui
        import win32process

        from src import GAME_EXE, LAUNCHER_EXE

        names = {GAME_EXE.lower(), *(n.lower() for n in LAUNCHER_EXE)}
        pids = set()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if (proc.info.get("name") or "").lower() in names:
                    pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        lines = []

        def collect(hwnd, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return True
            if pid in pids:
                lines.append(
                    f"hwnd={hwnd} pid={pid} class={win32gui.GetClassName(hwnd)!r} "
                    f"title={win32gui.GetWindowText(hwnd)!r} "
                    f"visible={win32gui.IsWindowVisible(hwnd)} rect={win32gui.GetWindowRect(hwnd)}"
                )
            return True

        win32gui.EnumWindows(collect, None)
        task.log_info(f"游戏进程窗口列表({len(lines)}个):")
        for line in lines:
            task.log_info(f"  {line}")
    except Exception as e:
        task.log_info(f"诊断窗口枚举失败: {e}")
