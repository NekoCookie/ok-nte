"""[lw] Nanally super-jump macro hosted by the character config task."""

import json
import time

ENABLE = "启用娜娜莉超级跳"
HOTKEY = "超级跳触发按键"
JUMP_DELAY = "起跳延迟(s)"
SECOND_JUMP_DELAY = "第二跳延迟(s)"
MODE_SWITCH_DELAY = "切模式诱饵延迟(ms)"
KEYS = [ENABLE, HOTKEY, JUMP_DELAY, SECOND_JUMP_DELAY, MODE_SWITCH_DELAY]

DEFAULT_JUMP_DELAY = 0.48
DEFAULT_SECOND_JUMP_DELAY = 0.45
# 手柄经 Steam Input 映射成触发键时,触发瞬间游戏可能还在手柄模式,
# bot 发的第一下键鼠输入只用来切回键鼠模式、被吞掉。开跑真宏前先补发
# 一下"诱饵 click"把这次切模式吃掉,再隔这么久(ms)让模式注册完,真宏 3 连点才全落地。
# 单位毫秒;设为 0 = 关闭补偿(键鼠触发、或实测不掉第一下时就设 0,免得多点一下反而坏时机)。
DEFAULT_MODE_SWITCH_DELAY_MS = 10
MODE_SWITCH_DECOY_DOWN_TIME = 0.05
JUMP_KEY_DOWN_TIME = 0.05
BASE_MACRO_STEPS = [
    ("click", 0.05),
    ("sleep", 0.3),
    ("click", 0.05),
    ("sleep", 0.3),
    ("click", 0.05),
]

# 原独立任务 NanallySuperJumpTask 的配置键 -> 合并后的配置键。
LEGACY_TASK_NAME = "NanallySuperJumpTask"
LEGACY_KEY_MAP = {
    "_enabled": ENABLE,
    "触发按键": HOTKEY,
    "起跳延迟(s)": JUMP_DELAY,
    "第二跳延迟(s)": SECOND_JUMP_DELAY,
    "切模式诱饵延迟(ms)": MODE_SWITCH_DELAY,
}


def configure_nanally_super_jump(task):
    task.default_config.update({
        ENABLE: True,
        HOTKEY: "mouse4",
        JUMP_DELAY: DEFAULT_JUMP_DELAY,
        SECOND_JUMP_DELAY: DEFAULT_SECOND_JUMP_DELAY,
        MODE_SWITCH_DELAY: DEFAULT_MODE_SWITCH_DELAY_MS,
    })
    task.config_description.update({
        ENABLE: "开=游戏在前台时按触发键执行一次娜娜莉超级跳; 不受手动触发总开关影响",
        HOTKEY: "按下该键执行一次娜娜莉超级跳宏",
        JUMP_DELAY: "第3次左键结束后，到按下空格前的等待时间",
        SECOND_JUMP_DELAY: "第一次空格结束后，到按下第二次空格前的等待时间；设为0表示禁用第二跳",
        MODE_SWITCH_DELAY: (
            "手柄触发时,跑真宏前先补一下诱饵左键吃掉切输入模式,再等这么久(毫秒)让模式注册完;"
            "设为0关闭(键鼠触发就设0)"
        ),
    })


def legacy_values(path):
    """Read the old standalone task config file and map it onto the merged keys; {} if absent."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {new: data[old] for old, new in LEGACY_KEY_MAP.items() if old in data}


def _non_negative(config, key, default):
    try:
        return max(0.0, float(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def macro_steps(config):
    steps = [
        *BASE_MACRO_STEPS,
        ("sleep", _non_negative(config, JUMP_DELAY, DEFAULT_JUMP_DELAY)),
        ("key", "space", JUMP_KEY_DOWN_TIME),
    ]
    second_jump_delay = _non_negative(config, SECOND_JUMP_DELAY, DEFAULT_SECOND_JUMP_DELAY)
    if second_jump_delay > 0:
        steps.extend([
            ("sleep", second_jump_delay),
            ("key", "space", JUMP_KEY_DOWN_TIME),
        ])
    return steps


class NanallySuperJump:
    """Poll the trigger key and run one super jump per press while the game is focused."""

    def __init__(self, task):
        self.task = task
        self._key_was_down = False

    def reset(self):
        self._key_was_down = False

    def poll(self):
        """Return True when a macro ran this tick."""
        task = self.task
        if not task.config.get(ENABLE, False) or not task.is_foreground():
            self._key_was_down = False
            return False
        key_down = task._is_key_pressed(task.config.get(HOTKEY))
        edge = key_down and not self._key_was_down
        self._key_was_down = key_down
        if not edge:
            return False
        self.run_macro()
        return True

    def run_macro(self):
        task = self.task
        task.log_info("nanally super jump macro start")
        self._compensate_input_mode_switch()
        start = time.perf_counter()
        try:
            for step_index, step in enumerate(macro_steps(task.config), start=1):
                action = step[0]
                if action == "click":
                    task.log_info(
                        f"nanally super jump macro step={step_index} click "
                        f"at {time.perf_counter() - start:.3f}s down_time={step[1]:.3f}s"
                    )
                    task.click(down_time=step[1])
                elif action == "key":
                    task.log_info(
                        f"nanally super jump macro step={step_index} key={step[1]} "
                        f"at {time.perf_counter() - start:.3f}s down_time={step[2]:.3f}s"
                    )
                    task.send_key(step[1], down_time=step[2])
                else:
                    time.sleep(step[1])
        finally:
            task.log_info(
                f"nanally super jump macro end elapsed={time.perf_counter() - start:.3f}s"
            )

    def _compensate_input_mode_switch(self):
        """跑真宏前补一下诱饵 click,吃掉手柄→键鼠的切模式(否则真宏第一下被吞)。
        延迟单位毫秒,设为 0 时整段跳过(键鼠触发不需要)。"""
        delay_ms = _non_negative(self.task.config, MODE_SWITCH_DELAY, DEFAULT_MODE_SWITCH_DELAY_MS)
        if delay_ms <= 0:
            return
        self.task.log_info(f"input-mode decoy click, settle {delay_ms}ms before real macro")
        self.task.click(down_time=MODE_SWITCH_DECOY_DOWN_TIME)
        time.sleep(delay_ms / 1000.0)
