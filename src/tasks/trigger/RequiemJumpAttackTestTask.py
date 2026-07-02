import ctypes
import time

import win32api
import win32con
from ok import TriggerTask

from src.combat import requiem_combo
from src.tasks.BaseNTETask import BaseNTETask


class _MacroIO:
    """把宏任务的底层收发(前台硬件/后台发消息)适配成 requiem_combo 执行器要的 io 接口。"""

    def __init__(self, task):
        self._t = task

    def should_continue(self):
        return self._t._macro_should_continue()

    def mouse_down(self):
        self._t._mouse_down()

    def mouse_up(self):
        self._t._mouse_up()

    def space_down(self):
        self._t._space_down()

    def space_up(self):
        self._t._space_up()

    def sleep_ms(self, ms):
        time.sleep(ms / 1000.0)


class RequiemJumpAttackTestTask(BaseNTETask, TriggerTask):
    CONF_TRIGGER_KEY = "触发按键"
    CHECK_INTERVAL = 0.03
    END_RECOVERY = 0.15

    # 4A宏三种模式:
    #   原始录制: 回放用户录的鼠标宏(RECORDED_MACRO), 走框架 PostMessage 后台点击, 一次一轮。
    #   安魂曲(方案一)/闪双4a(方案二): 移植自 YiHuan-Macro 参考实现, 硬件级输入
    #     (mouse_event/keybd_event, 等价 SendInput)+ 精确逐点时序 + 左键空格同时跳。
    #     长按触发键循环执行、松手即停(每一步都查键是否还按着)。
    #     PostMessage 版狂点会被游戏判成"长按左键→进瞄准", 故这两个方案改用硬件输入。
    MODE_RECORDED = "原始录制"
    MODE_SCHEME_A = "安魂曲(方案一)"
    MODE_SCHEME_B = "闪双4a(方案二)"
    MODE_SCHEME_C = "精简4A跳A(方案三)"  # 从原始录制精简: 4下地面普攻 + 空格跳 + 跳A那下左键
    CONF_MACRO_MODE = "4A宏模式"
    # 触发方式: 长按循环(松手停) / 按一下开关循环(按一下开始一直循环, 再按一下停)。
    CONF_TRIGGER_MODE = "触发方式"
    TRIGGER_HOLD = "长按循环(松手停)"
    TRIGGER_TOGGLE = "按一下开/关循环"
    # 方案一/二的输入方式:
    #   前台(硬件): win32 mouse_event/keybd_event 硬件级注入, 需游戏在前台、操作真实鼠键(已验证能打出)。
    #   后台(发消息): 走框架 PostMessage(mouse_down/up + send_key_down/up)发给游戏窗口, 不动真实鼠键、
    #                 游戏可不在前台。是否吃后台点击取决于游戏, 故做成开关实测。
    INPUT_HW = "前台(硬件)"
    INPUT_BG = "后台(发消息)"
    CONF_INPUT_MODE = "方案输入方式"
    # 安魂曲实战: 触发闪避后强制平A的持续秒数(0.1间隔), 保证高伤闪避反击一定打出、
    # 不被技能/大招/切人打断。放这里方便实时调; 实战侧(Requiem)读这个值。0=关闭。
    CONF_DODGE_COUNTER = "安魂曲闪避反击强制平A(s)"
    # combo 起手前, 若紧接在闪避反击之后, 额外等这么久让反击后摇走完再落第一下(否则 combo 顺序乱)。
    # 只影响 combo 路径; 切人/技能/大招不等。0=不等。
    CONF_DODGE_COMBO_WAIT = "combo前闪避反击后摇等待(s)"

    # 方案三(精简4A跳A)的全部时序, 单位毫秒, 可实时调(默认见 requiem_combo.SCHEME_C_*)。
    # 前3下普攻共用同一"按住/间隔"; 第4下(长动画)单独; 空格与跳A/后摇单独。
    CONF_C_ATTACK_HOLD = "方案三-普攻按住(ms)"
    CONF_C_ATTACK_GAP = "方案三-前3普攻间隔(ms)"
    CONF_C_A4_HOLD = "方案三-第4下按住(ms)"
    CONF_C_A4_WAIT = "方案三-第4下长动画(ms)"
    CONF_C_JUMP_HOLD = "方案三-空格按住(ms)"
    CONF_C_JUMP_GAP = "方案三-空格后间隔(ms)"
    CONF_C_JUMPA_HOLD = "方案三-跳A按住(ms)"
    CONF_C_RECOVERY = "方案三-后摇(ms)"

    # 方案一/二的精确时序统一放在 src/combat/requiem_combo.py(宏与实战主C共用, 改一处两边同步)。
    # 一轮结束后, 若仍按着触发键, 停这么久再进下一轮(对齐参考的 Sleep(200))。
    SCHEME_LOOP_GAP = 0.200

    KEY_MAP = {
        "space": win32con.VK_SPACE,
        "shift": win32con.VK_SHIFT,
        "ctrl": win32con.VK_CONTROL,
        "control": win32con.VK_CONTROL,
        "alt": win32con.VK_MENU,
        "esc": win32con.VK_ESCAPE,
        "escape": win32con.VK_ESCAPE,
        "tab": win32con.VK_TAB,
        "enter": win32con.VK_RETURN,
        "return": win32con.VK_RETURN,
        "backspace": win32con.VK_BACK,
        "mouse4": 0x05,
        "mouse5": 0x06,
        "x1": 0x05,
        "x2": 0x06,
        "side1": 0x05,
        "side2": 0x06,
    }
    # Recorded from the user's working mouse macro:
    # repeated left click down/up timings, then Space, then follow-up left clicks.
    RECORDED_MACRO = [
        ("click", 0.096),
        ("sleep", 0.087),
        ("click", 0.064),
        ("sleep", 0.095),
        ("click", 0.068),
        ("sleep", 0.099),
        ("click", 0.072),
        ("sleep", 0.092),
        ("click", 0.084),
        ("sleep", 0.077),
        ("click", 0.085),
        ("sleep", 0.074),
        ("click", 0.093),
        ("sleep", 0.082),
        ("click", 0.098),
        ("sleep", 0.077),
        ("click", 0.092),
        ("sleep", 0.326),
        ("key", "space", 0.100),
        ("sleep", 0.002),
        ("click", 0.074),
        ("sleep", 0.042),
        # 最后一个平A: 原 0.082s 时宏总时长短于这一下的后摇, 连打第二轮时上一轮后摇还没走完
        # 就开下一轮→第二轮结尾错乱。把按住时长拉到 0.25s 盖住后摇, 单轮/连轮结尾都稳。
        ("click", 0.25),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.default_config.update(
            {
                self.CONF_TRIGGER_KEY: "mouse5",
                self.CONF_MACRO_MODE: self.MODE_SCHEME_A,
                self.CONF_TRIGGER_MODE: self.TRIGGER_HOLD,
                self.CONF_INPUT_MODE: self.INPUT_BG,
                self.CONF_DODGE_COUNTER: 0.3,
                self.CONF_DODGE_COMBO_WAIT: 0.3,
                self.CONF_C_ATTACK_HOLD: 80,
                self.CONF_C_ATTACK_GAP: 220,
                self.CONF_C_A4_HOLD: 80,
                self.CONF_C_A4_WAIT: 781,
                self.CONF_C_JUMP_HOLD: 100,
                self.CONF_C_JUMP_GAP: 2,
                self.CONF_C_JUMPA_HOLD: 74,
                self.CONF_C_RECOVERY: 275,
            }
        )
        self.config_type.update(
            {
                self.CONF_MACRO_MODE: {
                    "type": "drop_down",
                    "options": [
                        self.MODE_RECORDED, self.MODE_SCHEME_A,
                        self.MODE_SCHEME_B, self.MODE_SCHEME_C,
                    ],
                },
                self.CONF_TRIGGER_MODE: {
                    "type": "drop_down",
                    "options": [self.TRIGGER_HOLD, self.TRIGGER_TOGGLE],
                },
                self.CONF_INPUT_MODE: {
                    "type": "drop_down",
                    "options": [self.INPUT_HW, self.INPUT_BG],
                },
            }
        )
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "长按该键执行4A+跳A宏(方案一/二为长按循环, 松手即停)",
                self.CONF_MACRO_MODE: (
                    "4A宏模式: 原始录制 / 安魂曲(方案一) / 闪双4a(方案二) / 精简4A跳A(方案三)"
                ),
                self.CONF_TRIGGER_MODE: "触发方式: 长按循环(按住一直打, 松手停) / 按一下开关循环(按一下开始一直循环, 再按一下停)",
                self.CONF_INPUT_MODE: "仅方案一/二/三: 前台(硬件, 已验证) / 后台(发消息, 游戏可不在前台, 实测)",
                self.CONF_DODGE_COUNTER: "实战安魂曲触发闪避后强制平A的秒数(0.1间隔), 保证高伤闪避反击打出、不被打断; 0=关闭",
                self.CONF_DODGE_COMBO_WAIT: "实战安魂曲: combo 起手前若紧接闪避反击, 额外等这么久让反击后摇走完(否则combo乱序); 只影响combo, 切人/技能/大招不等; 0=不等",
                self.CONF_C_ATTACK_HOLD: "方案三 前3下普攻每下左键按住毫秒",
                self.CONF_C_ATTACK_GAP: "方案三 前3下普攻的间隔毫秒(攻击节拍; 太小会被吞成2下, 太大变慢)",
                self.CONF_C_A4_HOLD: "方案三 第4下普攻左键按住毫秒",
                self.CONF_C_A4_WAIT: "方案三 第4下长动画等待毫秒(跳A插在这段里; 决定空格落点)",
                self.CONF_C_JUMP_HOLD: "方案三 空格(跳)按住毫秒",
                self.CONF_C_JUMP_GAP: "方案三 空格之后到跳A左键的间隔毫秒",
                self.CONF_C_JUMPA_HOLD: "方案三 跳A那下左键按住毫秒",
                self.CONF_C_RECOVERY: "方案三 末尾后摇毫秒",
            }
        )
        self.name = "安魂曲跳A测试"
        self.description = "长按/按一下开关 触发键执行安魂曲4A+跳A宏"
        self._submitted = False
        self._key_was_down = False
        self._macro_running = False
        self._toggle_mode = False   # 本轮是否"按一下开关循环"
        self._toggle_stop = False   # toggle 循环收到停止(再按一下)
        self._tk_was_down = False   # toggle 里检测"再按一下"边沿用的键前态

    def run(self):
        if self._submitted:
            return
        self._submitted = True
        self.submit_periodic_task(self.CHECK_INTERVAL, self._loop)

    def _loop(self):
        if not self.enabled:
            self._submitted = False
            self._key_was_down = False
            self._macro_running = False
            return False

        # 后台发消息模式(方案一/二/三)允许游戏不在前台时执行; 其余(硬件/原始录制)仍要求前台。
        bg_mode = (
            self.config.get(self.CONF_MACRO_MODE) in (
                self.MODE_SCHEME_A, self.MODE_SCHEME_B, self.MODE_SCHEME_C)
            and self.config.get(self.CONF_INPUT_MODE) == self.INPUT_BG
        )
        if not bg_mode and not self.is_foreground():
            self._key_was_down = False
            return True

        key_down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        toggle = self.config.get(self.CONF_TRIGGER_MODE) == self.TRIGGER_TOGGLE
        if toggle:
            # 按一下开关循环: 检测按下边沿(松→按)。宏没在跑时的一次边沿=开始循环;
            # 循环里的"再按一下"由 _run_macro 内部(_check_toggle_stop)负责停, 不在这里。
            edge = key_down and not self._key_was_down
            self._key_was_down = key_down
            if edge and not self._macro_running:
                self._run_macro()
            return True

        # 长按循环: 松手即停
        if not key_down:
            self._key_was_down = False
            return True
        if self._key_was_down or self._macro_running:
            return True
        self._key_was_down = True
        self._run_macro()
        return True

    def _conf_num(self, key, default):
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _scheme_c_params(self):
        """方案三全部时序从配置读(可实时调): 前3下普攻共用按住/间隔, 第4下/空格/跳A/后摇各自。"""
        hold = self._conf_num(self.CONF_C_ATTACK_HOLD, 80)
        gap = self._conf_num(self.CONF_C_ATTACK_GAP, 220)
        return dict(
            ground=[(hold, gap), (hold, gap), (hold, gap),
                    (self._conf_num(self.CONF_C_A4_HOLD, 80), self._conf_num(self.CONF_C_A4_WAIT, 781))],
            jump_hold_ms=self._conf_num(self.CONF_C_JUMP_HOLD, 100),
            jump_gap_ms=self._conf_num(self.CONF_C_JUMP_GAP, 2),
            jumpa_click=(self._conf_num(self.CONF_C_JUMPA_HOLD, 74),
                         self._conf_num(self.CONF_C_RECOVERY, 275)),
        )

    def _scheme_runner(self, mode, io):
        """mode → (跑一轮的可调用, 显示名)。方案三的时序由配置实时决定。"""
        if mode == self.MODE_SCHEME_A:
            return (lambda: requiem_combo.run_scheme_a(io)), "安魂曲(方案一)"
        if mode == self.MODE_SCHEME_B:
            return (lambda: requiem_combo.run_scheme_b(io)), "闪双4a(方案二)"
        if mode == self.MODE_SCHEME_C:
            params = self._scheme_c_params()
            return (lambda: requiem_combo.run_scheme_c(io, **params)), "精简4A跳A(方案三)"
        return None

    def _run_macro(self):
        self._macro_running = True
        mode = self.config.get(self.CONF_MACRO_MODE, self.MODE_SCHEME_A)
        self._toggle_mode = self.config.get(self.CONF_TRIGGER_MODE) == self.TRIGGER_TOGGLE
        self.log_info(f"requiem jump attack macro start mode={mode} toggle={self._toggle_mode}")
        start = time.perf_counter()
        # 提高系统定时器精度到1ms, 否则 time.sleep 的几十ms被Windows默认~15ms粒度取整, 打乱连招节奏。
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            if mode in (self.MODE_SCHEME_A, self.MODE_SCHEME_B, self.MODE_SCHEME_C):
                self._prepare_input()
                io = _MacroIO(self)
                run_once, name = self._scheme_runner(mode, io)
                loop = self._run_scheme_loop_toggle if self._toggle_mode else self._run_scheme_loop
                loop(run_once, name)
            elif self._toggle_mode:
                # 原始录制 + 按一下开关循环: 循环回放直到再按一下。
                self._run_scheme_loop_toggle(
                    lambda: self._run_recorded_macro(time.perf_counter()), "原始录制")
            else:
                self._run_recorded_macro(start)
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            elapsed = time.perf_counter() - start
            self.log_info(f"requiem jump attack macro end mode={mode} elapsed={elapsed:.3f}s")
            self._macro_running = False

    def _macro_should_continue(self):
        """方案执行器每一下之前查: 长按模式=键还按着; toggle模式=没收到"再按一下"的停止。"""
        if self._toggle_mode:
            return not self._check_toggle_stop()
        return self._trigger_held()

    def _check_toggle_stop(self):
        """toggle 模式: 检测"又按了一下触发键"(先松后按的上升沿) → 置停止标志。"""
        down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        if down and not self._tk_was_down:
            self._toggle_stop = True
        self._tk_was_down = down
        return self._toggle_stop

    def _run_scheme_loop_toggle(self, run_once, name):
        """按一下开关循环: 先等启动这次按住松开(否则会被当成停止), 然后一直循环跑,
        直到"再按一下"(_check_toggle_stop, 方案内每下 + 每轮间都查)或任务停用。"""
        while self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY)):
            time.sleep(0.02)
        self._tk_was_down = False
        self._toggle_stop = False
        rounds = 0
        while self.enabled and not self._toggle_stop:
            run_once()
            rounds += 1
            if self._check_toggle_stop():
                break
            time.sleep(self.SCHEME_LOOP_GAP)
        self.log_info(f"requiem {name} toggle loop end rounds={rounds}")

    # ---------- 原始录制(PostMessage 后台点击) ----------
    def _run_recorded_macro(self, start):
        for step_index, step in enumerate(self.RECORDED_MACRO, start=1):
            action = step[0]
            if action == "click":
                down_time = step[1]
                self.log_info(
                    f"requiem jump attack macro step={step_index} click "
                    f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                )
                self.click(down_time=down_time)
            elif action == "key":
                key, down_time = step[1], step[2]
                self.log_info(
                    f"requiem jump attack macro step={step_index} key={key} "
                    f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                )
                self.send_key(key, down_time=down_time)
            else:
                time.sleep(step[1])
        time.sleep(self.END_RECOVERY)

    # ---------- 方案一/二(硬件输入, 长按循环, 松手即停) ----------
    def _trigger_held(self):
        """触发键是否仍被按住(且任务仍启用)。松手/停用即返回 False → 中止当前宏。"""
        return self.enabled and self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))

    def _prepare_input(self):
        """按配置决定方案一/二走硬件还是后台发消息。后台预取一次点击坐标(屏幕中心)的 lParam。"""
        self._bg = self.config.get(self.CONF_INPUT_MODE, self.INPUT_HW) == self.INPUT_BG
        self._itx = None
        self._bg_pos = 0
        if self._bg:
            self._itx = self.executor.interaction
            try:
                cx = round(self._itx.capture.width * 0.5)
                cy = round(self._itx.capture.height * 0.5)
                self._bg_pos = self._itx.update_mouse_pos(cx, cy)
            except Exception as e:
                self.log_info(f"bg input prepare pos failed, fallback center: {e}")
                self._bg_pos = self._itx.update_mouse_pos(-1, -1)

    def _mouse_down(self):
        if getattr(self, "_bg", False):
            self._itx.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, self._bg_pos)
        else:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def _mouse_up(self):
        if getattr(self, "_bg", False):
            self._itx.post(win32con.WM_LBUTTONUP, 0, self._bg_pos)
        else:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _space_down(self):
        if getattr(self, "_bg", False):
            self._itx.send_key_down("space")
        else:
            win32api.keybd_event(win32con.VK_SPACE, 0, 0, 0)

    def _space_up(self):
        if getattr(self, "_bg", False):
            self._itx.send_key_up("space")
        else:
            win32api.keybd_event(win32con.VK_SPACE, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _run_scheme_loop(self, scheme, name):
        """长按触发键→循环执行一轮方案, 松手即停(对齐参考 MacroEngineThread)。
        scheme 为跑一轮的可调用(内部按 io.should_continue 逐点查触发键, 松手即停)。"""
        rounds = 0
        while self._trigger_held():
            scheme()
            rounds += 1
            if self._trigger_held():
                time.sleep(self.SCHEME_LOOP_GAP)
        self.log_info(f"requiem {name} loop end rounds={rounds}")

    def _is_key_pressed(self, key):
        vk_code = self._get_vk_code(key)
        return vk_code is not None and bool(win32api.GetAsyncKeyState(vk_code) & 0x8000)

    def _get_vk_code(self, key):
        if key is None:
            return None

        key = str(key).strip().lower()
        if not key:
            return None

        if key in self.KEY_MAP:
            return self.KEY_MAP[key]
        if key.startswith("f") and key[1:].isdigit():
            index = int(key[1:])
            if 1 <= index <= 12:
                return win32con.VK_F1 + index - 1
        if len(key) == 1:
            vk_code = win32api.VkKeyScan(key)
            if vk_code == -1:
                return None
            return vk_code & 0xFF

        return None
