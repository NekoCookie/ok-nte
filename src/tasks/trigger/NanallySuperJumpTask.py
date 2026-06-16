import time

import win32api
import win32con
from ok import TriggerTask

from src.tasks.BaseNTETask import BaseNTETask


class NanallySuperJumpTask(BaseNTETask, TriggerTask):
    CONF_TRIGGER_KEY = "触发按键"
    CONF_JUMP_DELAY = "起跳延迟(s)"
    CONF_SECOND_JUMP_DELAY = "第二跳延迟(s)"
    CONF_MODE_SWITCH_DELAY = "切模式诱饵延迟(ms)"
    CHECK_INTERVAL = 0.03
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
    BASE_MACRO_STEPS = [
        ("click", 0.05),
        ("sleep", 0.3),
        ("click", 0.05),
        ("sleep", 0.3),
        ("click", 0.05),
    ]
    DEFAULT_JUMP_DELAY = 0.48
    DEFAULT_SECOND_JUMP_DELAY = 0.45
    JUMP_KEY_DOWN_TIME = 0.05
    # 手柄经 Steam Input 映射成触发键时,触发瞬间游戏可能还在手柄模式,
    # bot 发的第一下键鼠输入只用来切回键鼠模式、被吞掉。开跑真宏前先补发
    # 一下"诱饵 click"把这次切模式吃掉,再隔这么久(ms)让模式注册完,真宏 3 连点才全落地。
    # 单位毫秒;设为 0 = 关闭补偿(键鼠触发、或实测不掉第一下时就设 0,免得多点一下反而坏时机)。
    DEFAULT_MODE_SWITCH_DELAY_MS = 10
    MODE_SWITCH_DECOY_DOWN_TIME = 0.05

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.default_config.update(
            {
                self.CONF_TRIGGER_KEY: "mouse4",
                self.CONF_JUMP_DELAY: self.DEFAULT_JUMP_DELAY,
                self.CONF_SECOND_JUMP_DELAY: self.DEFAULT_SECOND_JUMP_DELAY,
                self.CONF_MODE_SWITCH_DELAY: self.DEFAULT_MODE_SWITCH_DELAY_MS,
            }
        )
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "按下该键执行一次娜娜莉超级跳宏",
                self.CONF_JUMP_DELAY: "第3次左键结束后，到按下空格前的等待时间",
                self.CONF_SECOND_JUMP_DELAY: "第一次空格结束后，到按下第二次空格前的等待时间；设为0表示禁用第二跳",
                self.CONF_MODE_SWITCH_DELAY: "手柄触发时,跑真宏前先补一下诱饵左键吃掉切输入模式,再等这么久(毫秒)让模式注册完;设为0关闭(键鼠触发就设0)",
            }
        )
        self.name = "娜娜莉超级跳"
        self.description = "游戏在前台时，按触发键执行一次娜娜莉超级跳"
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
        self.log_info("nanally super jump macro start")
        self._compensate_input_mode_switch()
        start = time.perf_counter()
        try:
            for step_index, step in enumerate(self._get_macro_steps(), start=1):
                action = step[0]
                if action == "click":
                    down_time = step[1]
                    self.log_info(
                        f"nanally super jump macro step={step_index} click "
                        f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                    )
                    self.click(down_time=down_time)
                elif action == "key":
                    key, down_time = step[1], step[2]
                    self.log_info(
                        f"nanally super jump macro step={step_index} key={key} "
                        f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                    )
                    self.send_key(key, down_time=down_time)
                else:
                    time.sleep(step[1])
        finally:
            elapsed = time.perf_counter() - start
            self.log_info(f"nanally super jump macro end elapsed={elapsed:.3f}s")
            self._macro_running = False

    def _compensate_input_mode_switch(self):
        """跑真宏前补一下诱饵 click,吃掉手柄→键鼠的切模式(否则真宏第一下被吞)。
        延迟单位毫秒,设为 0 时整段跳过(键鼠触发不需要)。"""
        delay_ms = self._get_mode_switch_delay_ms()
        if delay_ms <= 0:
            return
        self.log_info(f"input-mode decoy click, settle {delay_ms}ms before real macro")
        self.click(down_time=self.MODE_SWITCH_DECOY_DOWN_TIME)
        time.sleep(delay_ms / 1000.0)

    def _get_mode_switch_delay_ms(self):
        try:
            delay_ms = float(
                self.config.get(self.CONF_MODE_SWITCH_DELAY, self.DEFAULT_MODE_SWITCH_DELAY_MS)
            )
        except (TypeError, ValueError):
            delay_ms = self.DEFAULT_MODE_SWITCH_DELAY_MS
        return max(0.0, delay_ms)

    def _get_macro_steps(self):
        jump_delay = self._get_jump_delay()
        steps = [
            *self.BASE_MACRO_STEPS,
            ("sleep", jump_delay),
            ("key", "space", self.JUMP_KEY_DOWN_TIME),
        ]
        second_jump_delay = self._get_second_jump_delay()
        if second_jump_delay > 0:
            steps.extend(
                [
                    ("sleep", second_jump_delay),
                    ("key", "space", self.JUMP_KEY_DOWN_TIME),
                ]
            )
        return steps

    def _get_jump_delay(self):
        try:
            jump_delay = float(self.config.get(self.CONF_JUMP_DELAY, self.DEFAULT_JUMP_DELAY))
        except (TypeError, ValueError):
            jump_delay = self.DEFAULT_JUMP_DELAY
        return max(0.0, jump_delay)

    def _get_second_jump_delay(self):
        try:
            second_jump_delay = float(
                self.config.get(self.CONF_SECOND_JUMP_DELAY, self.DEFAULT_SECOND_JUMP_DELAY)
            )
        except (TypeError, ValueError):
            second_jump_delay = self.DEFAULT_SECOND_JUMP_DELAY
        return max(0.0, second_jump_delay)

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
