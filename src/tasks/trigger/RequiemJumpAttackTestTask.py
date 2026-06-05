import time

import win32api
import win32con
from ok import TriggerTask

from src.char.CharFactory import char_dict
from src.char.Requiem import RequiemJumpAttackTest
from src.char.custom.CustomCharManager import CustomCharManager
from src.tasks.BaseNTETask import BaseNTETask


class RequiemJumpAttackTestTask(BaseNTETask, TriggerTask):
    CONF_TRIGGER_KEY = "触发按键"
    CHECK_INTERVAL = 0.03
    TEST_TEMPLATE_KEY = "template_requiem_4a_jump_test"
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
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": True}
        self.default_config.update({self.CONF_TRIGGER_KEY: "6"})
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "当前角色绑定安魂曲4a跳a测试模板时，按下该键执行一轮4A+跳A测试"
            }
        )
        self.name = "安魂曲跳A测试"
        self.description = "站在队伍界面时，按触发键执行当前槽位绑定的安魂曲4A+跳A测试模板"
        self._submitted = False
        self._key_was_down = False

    def run(self):
        if self._submitted:
            return
        self._submitted = True
        self.submit_periodic_task(self.CHECK_INTERVAL, self._loop)

    def _loop(self):
        if not self.enabled:
            self._submitted = False
            self._key_was_down = False
            return False

        if not self.is_foreground():
            self._key_was_down = False
            return True

        key_down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        if not key_down:
            self._key_was_down = False
            return True
        if self._key_was_down:
            return True
        self._key_was_down = True

        self._run_current_slot_test()
        return True

    def _run_current_slot_test(self):
        in_team, current_index, _ = self.in_team()
        if not in_team or current_index < 0:
            self.log_info("requiem jump attack test ignored: not in team")
            return

        manager = CustomCharManager()
        fixed_team = manager.get_fixed_team()
        if not fixed_team.get("enabled", False):
            self.log_info("requiem jump attack test ignored: fixed team is not enabled")
            return

        slots = fixed_team.get("slots", [])
        if current_index >= len(slots):
            self.log_info(f"requiem jump attack test ignored: no fixed slot {current_index + 1}")
            return

        slot = slots[current_index]
        combo_ref = manager.to_combo_ref(str(slot.get("combo_ref", "") or "").strip())
        builtin_key = manager.get_builtin_key(combo_ref)
        if builtin_key != self.TEST_TEMPLATE_KEY:
            self.log_info(
                "requiem jump attack test ignored: current slot is not bound to a test template"
            )
            return

        cls = char_dict.get(builtin_key, {}).get("cls")
        if cls is None or not issubclass(cls, RequiemJumpAttackTest):
            self.log_info(f"requiem jump attack test ignored: invalid template {builtin_key}")
            return

        char_name = str(slot.get("char_name", "") or "Requiem")
        test_char = cls(self, current_index, char_name=char_name, confidence=1)
        self.log_info(
            f"requiem jump attack test trigger slot={current_index + 1} "
            f"template={manager.to_combo_label(combo_ref)}"
        )
        test_char.do_perform()
        time.sleep(0.05)

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
