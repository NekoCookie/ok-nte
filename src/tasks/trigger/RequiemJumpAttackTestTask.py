import time

import win32api
import win32con
from ok import TriggerTask

from src.tasks.BaseNTETask import BaseNTETask


class RequiemJumpAttackTestTask(BaseNTETask, TriggerTask):
    CONF_TRIGGER_KEY = "触发按键"
    CHECK_INTERVAL = 0.03
    END_RECOVERY = 0.15
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
        ("click", 0.082),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.default_config.update({self.CONF_TRIGGER_KEY: "6"})
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "按下该键执行一轮安魂曲4A+跳A宏"
            }
        )
        self.name = "安魂曲跳A测试"
        self.description = "游戏在前台时，按触发键执行一轮安魂曲4A+跳A宏"
        self._submitted = False
        self._key_was_down = False
        self._macro_running = False

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

        if not self.is_foreground():
            self._key_was_down = False
            return True

        key_down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        if not key_down:
            self._key_was_down = False
            return True
        if self._key_was_down or self._macro_running:
            return True

        self._key_was_down = True
        self._run_macro()
        return True

    def _run_macro(self):
        self._macro_running = True
        self.log_info("requiem jump attack recorded macro start")
        start = time.perf_counter()
        try:
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
        finally:
            elapsed = time.perf_counter() - start
            self.log_info(f"requiem jump attack recorded macro end elapsed={elapsed:.3f}s")
            self._macro_running = False

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
