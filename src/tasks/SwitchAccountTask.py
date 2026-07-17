# [lw] 用户自有任务: 自动切换账号(UI流, 全程后台操作)。
# 依赖 HOTTA SDK 登录器已"记住"多个账号(免密点选), 流程:
# 游戏内 back_to_login → 登录界面点"退出账号" → 确认 → HOTTA面板展开账号列表
# → OCR认UID点目标账号 → 登录 → ensure_main 点"进入游戏"回世界。
#
# 关键: HOTTA 面板不是游戏内UI, 而是启动器进程(NTEGame.exe)的独立全屏顶层窗口
# (类名 Qt51517QWindowToolSaveBitsOwnDC, 2026-07-18 窗口枚举诊断实锤)。
# 游戏窗口的 WGC 捕获帧里没有它, PostMessage 发给游戏 hwnd 也点不到它,
# 因此面板阶段的识别与点击由 HottaPanel 单独完成: 桌面抓屏该窗口区域 → task.ocr(frame=)
# → PostMessage 直发 SDK 窗口 hwnd(不动真实鼠标, 仍是后台操作)。
#
# 切号流程写成模块级函数(接收task参数): DailyTask 的"跑完自动换号再跑一轮"钩子
# (src/lw/nte_task_ext.py 的 lw_daily_account_cycle)在 DailyTask 自身实例上执行,
# 避免跨任务实例调用 sleep/operate 的运行态问题。
import re

import numpy as np
from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask

# UID为8~10位纯数字整行; 手机号行含掩码星号(或吞星号后仅7位), 均不会误匹配
UID_RE = re.compile(r"^\d{8,10}$")
# 全匹配"登录"两字, 避免点到下方的"使用其他方式登录"
LOGIN_BTN_RE = re.compile(r"^登\s*录$")

# 登录界面右侧竖排图标第4个: "退出账号"(设置/公告/客服之下的门形图标), 游戏窗口内UI
LOGOUT_ICON = (0.9715, 0.3156)
# 退出账号确认弹窗的按钮行(游戏窗口内UI), 罩住取消+确认, find_confirm 会OCR认字挑"确认"
CONFIRM_RANGE = (0.28, 0.60, 0.72, 0.72)
# 以下均为 HOTTA SDK 面板窗口内的归一化坐标(窗口全屏, 与屏幕归一化一致)
# 面板整体区域(OCR用, 避开四周杂字)
PANEL_RANGE = (0.35, 0.19, 0.65, 0.80)
# 折叠态当前账号行右端的下拉箭头。注意: 展开态同位置是"删除账号"垃圾桶,
# 必须确认面板处于折叠态(仅1个UID可见)才允许点这里
DROPDOWN_ARROW = (0.5975, 0.391)

# SDK 面板窗口识别: 启动器进程的可见大窗口, 类名含此关键字
SDK_CLASS_HINT = "QWindowToolSaveBitsOwnDC"


class SwitchAccountTask(NTEOneTimeTask, BaseNTETask):
    CONF_TARGET_UID = "目标账号UID"
    CONF_CYCLE_WITH_DAILY = "日常跑完自动换号再跑一轮"
    CONF_SWITCH_BACK = "第二轮跑完切回原账号"

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
                self.CONF_SWITCH_BACK: False,
            }
        )
        self.config_description.update(
            {
                self.CONF_TARGET_UID: "登录面板账号条目下方的数字ID; 留空=自动切到列表中另一个账号",
                self.CONF_CYCLE_WITH_DAILY: "运行日常任务时, 跑完自动切到另一个账号再跑一轮日常(无需手动运行本任务)",
                self.CONF_SWITCH_BACK: "第二轮日常跑完后, 自动切回第一轮所在的账号",
            }
        )
        # 切回开关仅在轮换开关打开时展示
        self.config_type.update(
            {
                self.CONF_CYCLE_WITH_DAILY: {
                    "sub_configs": {True: [self.CONF_SWITCH_BACK]},
                },
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


class HottaPanel:
    """HOTTA SDK 登录面板窗口的识别与点击通道。

    面板是启动器进程的独立顶层窗口, 游戏捕获看不见、游戏 hwnd 收不到它的点击。
    这里对该窗口: 桌面抓屏其区域(要求窗口在前台可见, 调用方先 bring_to_front)
    → 走 task.ocr(frame=) 识别 → PostMessage 直发该窗口做后台点击。
    """

    def __init__(self, task):
        self.task = task
        self.hwnd = None

    def attach(self):
        """找到可见的 SDK 面板窗口, 返回是否存在。"""
        self.hwnd = _find_sdk_hwnd()
        return self.hwnd is not None

    def gone(self):
        return _find_sdk_hwnd() is None

    def frame(self):
        """桌面抓屏面板窗口区域, 返回BGR ndarray; 窗口无效返回 None。"""
        import win32con
        import win32gui
        import win32ui

        hwnd = self.hwnd
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None
        desktop_dc = mfc_dc = mem_dc = bmp = None
        try:
            desktop_dc = win32gui.GetWindowDC(win32gui.GetDesktopWindow())
            mfc_dc = win32ui.CreateDCFromHandle(desktop_dc)
            mem_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            mem_dc.SelectObject(bmp)
            mem_dc.BitBlt((0, 0), (w, h), mfc_dc, (left, top), win32con.SRCCOPY)
            buf = bmp.GetBitmapBits(True)
            img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
            return np.ascontiguousarray(img)
        except Exception as e:
            self.task.log_info(f"HottaPanel 抓屏失败: {e}")
            return None
        finally:
            try:
                if bmp is not None:
                    win32gui.DeleteObject(bmp.GetHandle())
                if mem_dc is not None:
                    mem_dc.DeleteDC()
                if mfc_dc is not None:
                    mfc_dc.DeleteDC()
                if desktop_dc is not None:
                    win32gui.ReleaseDC(win32gui.GetDesktopWindow(), desktop_dc)
            except Exception:
                pass

    def ocr(self, match):
        img = self.frame()
        if img is None:
            return []
        x, y, to_x, to_y = PANEL_RANGE
        return self.task.ocr(x=x, y=y, to_x=to_x, to_y=to_y, frame=img, match=match) or []

    def read_uids(self):
        return self.ocr(UID_RE)

    def find_login_button(self):
        results = self.ocr(LOGIN_BTN_RE)
        return results[0] if results else None

    def click(self, rx, ry):
        """按窗口内归一化坐标 PostMessage 后台点击。"""
        import win32gui

        left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        px = int(rx * (right - left))
        py = int(ry * (bottom - top))
        self._post_click(px, py)

    def click_box(self, box):
        """点击 ocr 返回的 box(坐标为面板帧内像素)中心。"""
        self._post_click(box.x + box.width // 2, box.y + box.height // 2)

    def _post_click(self, px, py):
        import win32api
        import win32con
        import win32gui

        left, top, _, _ = win32gui.GetWindowRect(self.hwnd)
        cx, cy = win32gui.ScreenToClient(self.hwnd, (left + px, top + py))
        lparam = win32api.MAKELONG(cx, cy)
        self.task.log_info(f"HottaPanel click client=({cx}, {cy})")
        win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
        self.task.sleep(0.05)
        win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        self.task.sleep(0.05)
        win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        self.task.sleep(0.05)


def _find_sdk_hwnd():
    """枚举启动器进程的顶层窗口, 找可见的全屏 SDK 面板窗口。"""
    import psutil
    import win32gui
    import win32process

    from src import LAUNCHER_EXE

    names = {n.lower() for n in LAUNCHER_EXE}
    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() in names:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not pids:
        return None

    found = []

    def collect(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid not in pids or not win32gui.IsWindowVisible(hwnd):
            return True
        if SDK_CLASS_HINT not in win32gui.GetClassName(hwnd):
            return True
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if (right - left) < 800 or (bottom - top) < 600:
            return True  # 排除小弹窗
        found.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    return found[0] if found else None


def switch_account(task, target=""):
    """在任意 BaseNTETask 实例上执行完整切号流程。

    返回 (切到的UID, 切换前的UID或None); 切换前UID供"切回原账号"用。
    """
    panel = HottaPanel(task)
    ensure_at_login_screen(task)
    open_account_panel(task, panel)
    chosen, previous = select_account(task, panel, target)
    login_and_enter(task, panel, chosen)
    return chosen, previous


# ---- 步骤 ----


def ensure_at_login_screen(task):
    if not at_login_screen(task):
        task.log_info("当前在游戏内, 先退出到登录界面")
        task.back_to_login()
        if not task.wait_until(lambda: at_login_screen(task), time_out=60, raise_if_not_found=False):
            raise RuntimeError("未能回到登录界面")
    # SDK 面板窗口靠桌面抓屏识别, 必须保证游戏(及盖在上面的面板)在前台可见
    if not task.is_foreground():
        task.bring_to_front()
        task.sleep(3)


def open_account_panel(task, panel):
    if panel.attach() and panel.read_uids():
        task.log_info("HOTTA 账号面板已打开")
        return
    task.operate_click(*LOGOUT_ICON, after_sleep=1)
    task.wait_click_confirm(range=CONFIRM_RANGE, time_out=10)
    if not task.wait_until(
        lambda: panel.attach() and panel.read_uids(), time_out=20, raise_if_not_found=False
    ):
        dump_panel_diagnostics(task, panel)
        raise RuntimeError("退出账号后 HOTTA 账号面板未出现(诊断截图与窗口列表已存日志)")
    task.log_info(f"HOTTA 面板窗口 hwnd={panel.hwnd}")


def select_account(task, panel, target):
    """返回 (选中的UID, 面板打开时折叠态显示的原UID或None)。"""
    uids = panel.read_uids()
    current = uids[0].name if len(uids) == 1 else None
    if target and current == target:
        task.log_info(f"面板当前已选中目标账号 {target}")
        return target, current
    if current is not None:
        # 折叠态: 点箭头展开账号列表
        panel.click(*DROPDOWN_ARROW)
        task.sleep(1)
    row = task.wait_until(
        lambda: find_target_row(panel, target, current), time_out=10, raise_if_not_found=False
    )
    if not row:
        raise RuntimeError(f"账号列表中没找到目标账号: {target or '<另一个账号>'}")
    chosen = row.name
    task.log_info(f"点选账号 {chosen}")
    panel.click_box(row)
    task.sleep(1)
    if not task.wait_until(
        lambda: collapsed_current(panel) == chosen, time_out=8, raise_if_not_found=False
    ):
        raise RuntimeError(f"点选账号 {chosen} 后面板未收起到该账号")
    return chosen, current


def login_and_enter(task, panel, chosen):
    login_btn = task.wait_until(panel.find_login_button, time_out=8, raise_if_not_found=False)
    if not login_btn:
        raise RuntimeError("HOTTA 面板上没找到登录按钮")
    panel.click_box(login_btn)
    task.sleep(2)
    # SDK登录完成后面板窗口消失, 回到"进入游戏"界面
    if not task.wait_until(
        lambda: panel.gone() and at_login_screen(task),
        time_out=60,
        raise_if_not_found=False,
    ):
        raise RuntimeError("点登录后 HOTTA 面板未关闭")
    task.scene.set_logged_in(False)
    task.log_info(f"账号已切到 {chosen}, 开始进入游戏")
    task.ensure_main(time_out=120)
    task.log_info(f"切换账号完成: {chosen}", notify=True)


# ---- 识别(游戏窗口侧) ----


def at_login_screen(task):
    # login_setting=登录界面右上角齿轮(游戏窗口内, 不被SDK面板遮挡判定)
    return bool(task.find_one(Labels.login_setting))


def collapsed_current(panel):
    uids = panel.read_uids()
    return uids[0].name if len(uids) == 1 else None


def find_target_row(panel, target, current):
    uids = panel.read_uids()
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


# ---- 诊断 ----


def dump_panel_diagnostics(task, panel=None):
    """面板等不到时: 存游戏捕获帧 + SDK窗口抓屏帧 + 枚举游戏/启动器进程的全部顶层窗口。"""
    try:
        task.screenshot("switch_account_no_panel")
    except Exception as e:
        task.log_info(f"诊断截图失败: {e}")
    try:
        if panel is not None and panel.attach():
            img = panel.frame()
            if img is not None:
                task.screenshot("switch_account_sdk_window", frame=img)
    except Exception as e:
        task.log_info(f"SDK窗口诊断截图失败: {e}")
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
