import ctypes
import os
import shutil
import time

import win32api
import win32con
from ok import TriggerTask
from ok.util.config import Config
from ok.util.file import get_relative_path

from src.combat import requiem_combo
from src.lw.activity import ActivityController, configure_activity  # [lw]
from src.lw.config_group import config_group, config_group_keys  # [lw]
from src.lw.requiem_zankou_axis import (
    CoordinatedAxisSettings,
    RequiemZankouAxisTester,
)
from src.tasks.BaseNTETask import BaseNTETask


class _MacroIO:
    """把宏任务的框架输入收发适配成 requiem_combo 执行器要的 io 接口。"""

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


class _CoaxisIO:
    """[lw] Adapt task input primitives to the standalone coordinated-axis tester."""

    ATTACK_DOWN_SECONDS = 0.02

    def __init__(self, task):
        self._task = task

    def enabled(self):
        return self._task.enabled and self._task._manual_key_triggers_enabled()

    def trigger_pressed(self, key):
        return self._task._is_key_pressed(key)

    def send_key(self, key):
        return self._task._coaxis_send_key(key)

    def tap_attack(self):
        self._task._mouse_down()
        try:
            time.sleep(self.ATTACK_DOWN_SECONDS)
        finally:
            self._task._mouse_up()

    def attack_down(self):
        self._task._mouse_down()

    def attack_up(self):
        self._task._mouse_up()

    def log(self, message):
        self._task.log_info(message)


class RequiemCombatConfigTask(BaseNTETask, TriggerTask):
    LEGACY_CONFIG_NAME = "RequiemJumpAttackTestTask"
    CONF_TRIGGER_KEY = "触发按键"
    CHECK_INTERVAL = 0.03

    # 4A宏: 长按(或按一下开关)触发键循环跑光速4a combo, 输入走框架 interaction(和自动战斗同一路)。
    # 触发方式: 长按循环(松手停) / 按一下开关循环(按一下开始一直循环, 再按一下停)。
    CONF_TRIGGER_MODE = "触发方式"
    TRIGGER_HOLD = "长按循环(松手停)"
    TRIGGER_TOGGLE = "按一下开/关循环"
    # 安魂曲实战: 真技能前先起手平A进入交战这么久(防开战瞬间直接放技能打空); 0=不补。
    # 原在"自动战斗"界面, 挪来这里统一; 实战侧(Requiem)读这个值。
    CONF_ENGAGE_ATTACK = "安魂曲技能前平A(s)"
    # 闪避反击测试开关: 打开后本任务专门测闪双4a时序 —— 关掉自动战斗、开这个, 每次声音闪避触发就
    # 执行[双4a → 尾段跳A → 补平A → N轮combo]。开启时忽略触发键宏, 只等声音闪避。
    CONF_DODGE_TEST = "闪避反击测试开关"  # 布尔开关(SwitchButton); 改过名, 让旧的下拉字符串值作废
    # 实战测试开关: 开=所有 LW 角色模板不放 E/Q, 方便单独测普攻手感 + 闪避。实战读它。
    CONF_DISABLE_SKILLS = "禁用技能大招(测试)"  # 布尔开关
    # 实战 combo 中途每隔这么久复查一次脱战: 目标被打死/打空则立即收手, 不再对着尸体空打完整轮 combo
    # (早雾那种"死了秒停手"的体感)。只影响主站场 combo; 双4a 等精调时序段不查, 免插帧扰乱跳A时机。
    # 用框架带去抖(2帧miss+0.4s)的 in_combat 判定, 不会因血条闪一下误停。实战侧(Requiem)读它; 0=关。
    CONF_COMBO_COMBAT_CHECK = "combo中途脱战复查(s)"
    # 实战 combo 跑到"进度 < 此比例(0~1)"时, 若技能/大招已就绪就中断本轮 combo、交回主循环去开。
    # 伤害大头在 combo 尾(跳A), 故只在前半让路; 进度过半(>=此值)一律打完不打断(不丢尾伤)。
    # 复用脱战复查那一下(每约0.5s)顺带查一次, 不额外插帧。实战侧(Requiem)读它; 0=关(永不为技能中断)。
    CONF_COMBO_BREAK_FOR_SKILL = "combo为技能大招让路(进度<)"
    # G技能(按G触发的那个图标): 开关开启后, 安魂曲每轮决策最优先检测屏幕右下G圆圈图标——
    # 图标从基线(平底锅)变成别的图标=技能就绪, 立即按G触发, 再等一段可配的后摇延迟(ms),
    # 便于测量"按下G到能接下一招(如大招)"的后摇。基线模板/匹配阈值在实战侧(Requiem)。
    CONF_G_SKILL_ENABLE = "G技能图标变化自动触发"   # 布尔开关
    CONF_G_SKILL_DELAY = "G技能按下后摇延迟(ms)"     # 按G后等这么久再交回决策(测后摇/接大招)
    DODGE_TEST_COMBO_ROUNDS = 2  # 测试里双4a后接几轮 combo 的默认值(配置读不到时用)
    CONF_COMBO_ROUNDS = "combo轮数"  # 测试里双4a/免费技能打断之后接几轮 combo, 可配
    # 闪双4a(声音闪避版)的可调时序: 声音闪避后 → 前段平A(打第一个4a) → 跳A(空格+左键同按)代替
    # 第二次闪避、续段 → 后段平A(接第二个4a)。三段时长各自可配, 前后平A共用连点按下/抬起
    # (逻辑同光速4a)。精确时序在 requiem_combo.run_scheme_double_4a。
    CONF_D4_FRONT = "双4a-前段平A(ms)"       # 第一个4a: 跳A之前的平A时长
    CONF_D4_JUMP_HOLD = "双4a-跳A按住(ms)"    # 空格+左键同时按住(代替闪避)
    CONF_D4_BACK = "双4a-后段平A(ms)"        # 第二个4a: 跳A之后的平A时长
    CONF_D4_CLICK_HOLD = "双4a-连点按住(ms)"  # 前后两段平A共用的左键按住
    CONF_D4_CLICK_GAP = "双4a-连点抬起(ms)"   # 前后两段平A共用的左键抬起
    # 两个4a打完后用跳A(空格+左键同按, 时长复用光速4a的"跳A按住")代替闪避, 再补平A。
    CONF_D4_TAIL_FILL = "双4a-闪避后补平A(ms)"  # 跳A后补平A的时长(平A节拍复用光速4a连点按住/抬起)
    DODGE_KEY = "lshift"  # 游戏闪避键(免费技能打断/闪避测试用)
    # 模拟声音闪避的测试键: 按一下=假装出现了声音闪避, 走一整轮完整流程[初始闪避→双4a→N轮combo],
    # 整轮暂停声音自动闪避。不用真声音、不受敌人干扰, 最适合看清流程。留空=关闭。
    CONF_DODGE_TEST_KEY = "闪避反击模拟测试键"

    # 光速4a(时间驱动)的可调时序, 单位毫秒(默认见 requiem_combo.SCHEME_LS_*)。
    # 核心是"跳A时机": 连点累计到这个时刻才左键+空格同跳, 改它时跳A那下左键自动跟着移动。
    CONF_LS_EXPAND = "方案四·光速4a时序"  # 折叠分组, 展开=5个时序配置
    CONF_LS_JUMP_AT = "方案四-跳A时机(ms)"
    CONF_LS_JUMP_HOLD = "方案四-跳A按住(ms)"
    CONF_LS_CLICK_HOLD = "方案四-连点按住(ms)"
    CONF_LS_CLICK_GAP = "方案四-连点抬起(ms)"
    CONF_LS_TAIL = "方案四-跳后收尾(ms)"

    # 免费技能后普攻会顺出又慢又低伤的第五下平A(a5)。放完免费技能用闪避打断它、不打那第五下,
    # 直接接 combo。以下时序可调(ms), 实战侧(Requiem)读。
    # 测试键: 按一下=发技能键放(免费)技能 → delay → 闪避打断 → combo; 需在游戏里把技能设成免费技能(可反复放)。
    CONF_FREE_BREAK_EXPAND = "免费技能设置"  # 折叠分组, 展开=时序+测试键
    CONF_FREE_BREAK_DELAY = "免费技能后打断延迟(ms)"      # 免费技能→闪避 的等待(核心旋钮)
    CONF_FREE_BREAK_JUMP_HOLD = "免费技能后闪避按住(ms)"  # 闪避键按住时长
    CONF_FREE_BREAK_WAIT = "免费技能后打断后等待(ms)"     # 闪避打断→combo第一下 的间隔
    CONF_FREE_BREAK_TEST_KEY = "免费技能后接combo测试键"
    CONF_FREE_SKILL_KEY = "技能键(测试放免费技能用)"

    # 顶层配置太多, 全部按用途折叠成组(默认收起, 用到再展开)。分组用 config_group() 声明,
    # [lw] 界面上渲染成和任务卡片一样的可展开标题(见 src/lw/config_group_ui.py), 不是开关。
    CONF_GROUP_TRIGGER = "基础触发设置"   # 折叠分组: 触发键/触发方式
    CONF_GROUP_SUPPORT_PREEMPTION = "辅助资源提权"
    CONF_SUPPORT_SKILL_SWITCH = "辅助技能就绪是否切人"
    CONF_SUPPORT_SKILL_PREEMPTION = "辅助E是否提权"
    CONF_SUPPORT_ULTIMATE_PREEMPTION = "辅助Q是否提权"
    # [lw] Requiem and Zankou main-DPS axis settings, folded away by default.
    CONF_GROUP_COAXIS = "安魂曲残虹合轴"
    CONF_COAXIS_COMBAT_ENABLE = "实战启用合轴"
    CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT = "入场提前执行技能大招"
    CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT = "安魂曲真技能后固定切人位置"
    CONF_COAXIS_TRIGGER_KEY = "合轴触发键"
    CONF_COAXIS_REQUIEM_SWITCH_KEY = "安魂曲切换键"
    CONF_COAXIS_ZANKOU_SWITCH_KEY = "残虹切换键"
    CONF_COAXIS_REQUIEM_DURATION = "安魂曲普攻时长(s)"
    CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION = "安魂曲免费技能后普攻时长(s)"
    CONF_COAXIS_ZANKOU_SWITCH_DELAY = "切到残虹后等待(s)"
    CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION = "残虹环合静默等待(s)"
    CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT = "残虹强化E打断合轴"
    CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL = "开局残虹黄E后切辅助"
    CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS = "黄E入场小怪也触发"
    CONF_COAXIS_ZANKOU_HOLD_DURATION = "残虹长按普攻时长(s)"
    CONF_COAXIS_ZANKOU_NORMAL_DURATION = "残虹普攻时长(s)"
    CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION = "残虹声音闪避后普攻时长(s)"
    CONF_ORDINARY_DODGE_WAIT = "普通闪避等待(s)"
    CONF_REQUIEM_ORDINARY_DODGE_WAIT = "安魂曲普通闪避等待(s)"
    CONF_GROUP_DODGE = "闪避反击设置"     # 折叠分组: 闪双4a时序
    CONF_GROUP_TUNING = "实战调优参数"    # 折叠分组
    CONF_GROUP_TEST = "测试开关与测试键"   # 折叠分组
    CONF_MANUAL_KEY_TRIGGERS = "启用手动触发按键"

    # 配置档位: 界面内保存/载入 1~4 套配置(存在 PRESET_FILE), 外加导出/从文件导入。
    CONF_GROUP_PRESET = "配置档位与导入导出"  # 折叠分组
    CONF_PRESET_SLOT = "配置档位"       # drop_down 1/2/3/4
    CONF_PRESET_OPS = "档位存取"        # 两个按钮: 保存到该档位 / 载入该档位
    CONF_PRESET_FILE = "配置文件"       # 两个按钮: 导出到文件 / 从文件导入
    PRESET_FILE = "configs/RequiemPresets.json"  # 4 套档位存这里
    EXCHANGE_DIRECTORY = "data_export"
    EXCHANGE_FILE_NAME = "安魂曲配置.json"

    # combo 的精确时序统一放在 src/combat/requiem_combo.py(宏与实战主C共用, 改一处两边同步)。
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.default_config.update(
            {
                # 默认值 = longwei 实测调优后的最优解(2026-07-05)。别的机器哪怕微调, 也从这套起,
                # 而不是最初那套(如光速4a跳A时机1470根本触发不了)。
                # 基础触发组(折叠): 触发键/触发方式
                self.CONF_GROUP_TRIGGER: False,
                self.CONF_TRIGGER_KEY: "mouse5",
                self.CONF_TRIGGER_MODE: self.TRIGGER_HOLD,
                # 辅助资源调度组: 默认保持当前行为; 可关闭 E 主动切人或 Q/E 环合前抢占。
                self.CONF_GROUP_SUPPORT_PREEMPTION: False,
                self.CONF_SUPPORT_SKILL_SWITCH: True,
                self.CONF_SUPPORT_SKILL_PREEMPTION: True,
                self.CONF_SUPPORT_ULTIMATE_PREEMPTION: True,
                # [lw] Pair-axis testing and default-off automatic-combat integration.
                self.CONF_GROUP_COAXIS: False,
                self.CONF_COAXIS_COMBAT_ENABLE: False,
                self.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT: False,
                self.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT: "关闭",
                self.CONF_COAXIS_TRIGGER_KEY: "8",
                self.CONF_COAXIS_REQUIEM_SWITCH_KEY: "1",
                self.CONF_COAXIS_ZANKOU_SWITCH_KEY: "2",
                self.CONF_COAXIS_REQUIEM_DURATION: 2.0,
                self.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 2.0,
                self.CONF_COAXIS_ZANKOU_SWITCH_DELAY: 0.5,
                self.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION: 1.5,
                self.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: False,
                self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: False,
                self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS: True,
                self.CONF_COAXIS_ZANKOU_HOLD_DURATION: 2.0,
                self.CONF_COAXIS_ZANKOU_NORMAL_DURATION: 2.0,
                self.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.5,
                self.CONF_ORDINARY_DODGE_WAIT: 0.5,
                self.CONF_REQUIEM_ORDINARY_DODGE_WAIT: 0.5,
                # 闪避反击设置组(折叠): 闪双4a时序
                self.CONF_GROUP_DODGE: False,
                self.CONF_D4_FRONT: 1800,
                self.CONF_D4_JUMP_HOLD: 20,
                self.CONF_D4_BACK: 700,
                self.CONF_D4_CLICK_HOLD: 20,
                self.CONF_D4_CLICK_GAP: 20,
                self.CONF_D4_TAIL_FILL: 250,
                # 光速4a时序(折叠)
                self.CONF_LS_EXPAND: False,
                self.CONF_LS_JUMP_AT: 1800,
                self.CONF_LS_JUMP_HOLD: 20,
                self.CONF_LS_CLICK_HOLD: 20,
                self.CONF_LS_CLICK_GAP: 20,
                self.CONF_LS_TAIL: 200,
                # 免费技能后闪避打断时序(折叠)
                self.CONF_FREE_BREAK_EXPAND: False,
                self.CONF_FREE_BREAK_DELAY: 250,
                self.CONF_FREE_BREAK_JUMP_HOLD: 20,
                self.CONF_FREE_BREAK_WAIT: 450,
                # 实战调优参数(折叠, 默认收起)
                self.CONF_GROUP_TUNING: False,
                self.CONF_COMBO_ROUNDS: 2,
                self.CONF_ENGAGE_ATTACK: 0.15,
                self.CONF_COMBO_COMBAT_CHECK: 0.5,
                self.CONF_COMBO_BREAK_FOR_SKILL: 0.5,
                self.CONF_G_SKILL_ENABLE: False,
                self.CONF_G_SKILL_DELAY: 300,
                # 测试开关与测试键(折叠, 默认收起)
                self.CONF_GROUP_TEST: False,
                self.CONF_MANUAL_KEY_TRIGGERS: False,
                self.CONF_DODGE_TEST: False,
                self.CONF_DISABLE_SKILLS: False,
                self.CONF_DODGE_TEST_KEY: "7",
                self.CONF_FREE_BREAK_TEST_KEY: "9",
                self.CONF_FREE_SKILL_KEY: "e",
            }
        )
        self.config_type.update(
            {
                self.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT: {
                    "type": "drop_down",
                    "options": ["关闭", "1", "2", "3", "4"],
                },
                # 光速4a那5个时序配置折叠成组, 展开才显示。
                self.CONF_LS_EXPAND: config_group([
                    self.CONF_LS_JUMP_AT, self.CONF_LS_JUMP_HOLD,
                    self.CONF_LS_CLICK_HOLD, self.CONF_LS_CLICK_GAP,
                    self.CONF_LS_TAIL,
                ]),
                # 基础触发组(折叠): 触发键/触发方式收进来, 不再裸露顶层。
                self.CONF_GROUP_TRIGGER: config_group([
                    self.CONF_TRIGGER_KEY, self.CONF_TRIGGER_MODE,
                ]),
                # 顶层折叠: 分别控制辅助 E/Q 是否发布 LW preemptive claim。
                self.CONF_GROUP_SUPPORT_PREEMPTION: config_group([
                    self.CONF_SUPPORT_SKILL_SWITCH,
                    self.CONF_SUPPORT_SKILL_PREEMPTION,
                    self.CONF_SUPPORT_ULTIMATE_PREEMPTION,
                ]),
                # [lw] Pair axis timings and its toggle key stay in one folded group.
                self.CONF_GROUP_COAXIS: config_group([
                    self.CONF_COAXIS_COMBAT_ENABLE,
                    self.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT,
                    self.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT,
                    self.CONF_COAXIS_TRIGGER_KEY,
                    self.CONF_COAXIS_REQUIEM_SWITCH_KEY,
                    self.CONF_COAXIS_ZANKOU_SWITCH_KEY,
                    self.CONF_COAXIS_REQUIEM_DURATION,
                    self.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION,
                    self.CONF_COAXIS_ZANKOU_SWITCH_DELAY,
                    self.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION,
                    self.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT,
                    self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL,
                    self.CONF_COAXIS_ZANKOU_HOLD_DURATION,
                    self.CONF_COAXIS_ZANKOU_NORMAL_DURATION,
                    self.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION,
                    self.CONF_ORDINARY_DODGE_WAIT,
                    self.CONF_REQUIEM_ORDINARY_DODGE_WAIT,
                ]),
                self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: {
                    "sub_configs": {
                        True: [self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS],
                    },
                },
                # 免费技能组(折叠): 闪避打断时序 + 测试键 全放一起。
                self.CONF_FREE_BREAK_EXPAND: config_group([
                    self.CONF_FREE_BREAK_DELAY, self.CONF_FREE_BREAK_JUMP_HOLD,
                    self.CONF_FREE_BREAK_WAIT,
                    self.CONF_FREE_BREAK_TEST_KEY, self.CONF_FREE_SKILL_KEY,
                ]),
                # 实战调优参数折叠: 展开才显示那几个秒数/比例旋钮(收起不影响其值生效)。
                self.CONF_GROUP_TUNING: config_group([
                    self.CONF_COMBO_ROUNDS, self.CONF_ENGAGE_ATTACK,
                    self.CONF_COMBO_COMBAT_CHECK, self.CONF_COMBO_BREAK_FOR_SKILL,
                    self.CONF_G_SKILL_ENABLE, self.CONF_G_SKILL_DELAY,
                ]),
                # 测试开关与测试键折叠: 展开才显示(收起不影响其值生效; 禁用技能大招默认关)。
                # 免费技能测试键在"免费技能组", 这里不再重复。
                self.CONF_GROUP_TEST: config_group([
                    self.CONF_MANUAL_KEY_TRIGGERS, self.CONF_DODGE_TEST,
                    self.CONF_DISABLE_SKILLS, self.CONF_DODGE_TEST_KEY,
                ]),
                self.CONF_TRIGGER_MODE: {
                    "type": "drop_down",
                    "options": [self.TRIGGER_HOLD, self.TRIGGER_TOGGLE],
                },
                # 闪避反击设置组(折叠): 闪双4a的6个时序。
                self.CONF_GROUP_DODGE: config_group([
                    self.CONF_D4_FRONT, self.CONF_D4_JUMP_HOLD, self.CONF_D4_BACK,
                    self.CONF_D4_CLICK_HOLD, self.CONF_D4_CLICK_GAP,
                    self.CONF_D4_TAIL_FILL,
                ]),
            }
        )
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "长按该键执行光速4a宏(松手即停)",
                self.CONF_TRIGGER_MODE: "长按循环(松手停) 或 按一下开/关循环",
                self.CONF_COMBO_ROUNDS: "测试里双4a/免费技能打断后接几轮combo",
                self.CONF_ENGAGE_ATTACK: "放真技能前先平A进交战这么久, 防打空; 0=不补",
                self.CONF_COMBO_COMBAT_CHECK: "实战combo中途每隔这么久复查脱战(目标死/打空即收手); 0=关",
                self.CONF_COMBO_BREAK_FOR_SKILL: "combo进度<此比例(0~1)且技能/大招就绪就中断去开(伤害大头在combo尾, 过半就打完); 0=关",
                self.CONF_G_SKILL_ENABLE: "开=右下G图标从基线(平底锅)变成别的图标时, 最优先按G触发",
                self.CONF_G_SKILL_DELAY: "按G后等这么久(ms)再交回决策; 用来测按下G的后摇(后面好接大招)",
                self.CONF_DODGE_TEST: "开=每次声音闪避走一整轮(关自动战斗后调时间用)",
                self.CONF_DISABLE_SKILLS: "开=所有LW角色模板不放E/Q; G和合轴不受影响(测手感/闪避用); 刷本记得关",
                self.CONF_GROUP_DODGE: "声音闪避后的闪双4a时序",
                self.CONF_D4_FRONT: "双4a 前段平A毫秒(打第一个4a); 太短会接不出第二个4a",
                self.CONF_D4_JUMP_HOLD: "双4a 跳A空格+左键同按毫秒(代替闪避)",
                self.CONF_D4_BACK: "双4a 后段平A毫秒(接第二个4a)",
                self.CONF_D4_CLICK_HOLD: "双4a 前后平A共用的左键按住毫秒",
                self.CONF_D4_CLICK_GAP: "双4a 前后平A共用的左键抬起毫秒",
                self.CONF_D4_TAIL_FILL: "双4a 两个4a后跳A(复用光速4a跳A按住), 再补平A这么多毫秒(节拍复用光速4a连点按住/抬起)",
                self.CONF_DODGE_TEST_KEY: "按此键=模拟一次声音闪避走整轮; 留空=关",
                self.CONF_LS_EXPAND: "光速4a的5个时序配置",
                self.CONF_LS_JUMP_AT: "方案四 跳A时机毫秒(核心); 大世界约1390其他约1470; 跳早出1a",
                self.CONF_LS_JUMP_HOLD: "方案四 跳A左键+空格同按毫秒(参考18)",
                self.CONF_LS_CLICK_HOLD: "方案四 连点每下左键按住毫秒",
                self.CONF_LS_CLICK_GAP: "方案四 连点每下左键抬起毫秒",
                self.CONF_LS_TAIL: "方案四 跳A后收尾毫秒(连点节拍继续平A填满; 参考218)",
                self.CONF_FREE_BREAK_TEST_KEY: "按此键=发技能键放(免费)技能→闪避打断a5→combo; 需游戏里把技能设成免费技能; 留空=关",
                self.CONF_FREE_SKILL_KEY: "测试放免费技能用的技能键(填游戏里的技能键, 如e)",
                self.CONF_FREE_BREAK_EXPAND: "免费技能后闪避打断a5的时序 + 免费技测试键/技能键",
                self.CONF_FREE_BREAK_DELAY: "免费技能放出→按闪避打断 之间等这么久(核心; 早了打断免费技能/晚了a5已出)",
                self.CONF_FREE_BREAK_JUMP_HOLD: "打断用的闪避键按住毫秒",
                self.CONF_FREE_BREAK_WAIT: "闪避打断→combo第一下 的间隔毫秒(可填0)",
                self.CONF_GROUP_TRIGGER: "触发键/触发方式",
                self.CONF_GROUP_SUPPORT_PREEMPTION: "辅助技能切人以及 Q/E 资源提权开关",
                self.CONF_SUPPORT_SKILL_SWITCH: "开=辅助 E 推算就绪时允许主动切人; 关=不因辅助 E 就绪切人",
                self.CONF_SUPPORT_SKILL_PREEMPTION: "开=允许切人时, 辅助 E 就绪会在环合前抢占; 关=仅按普通评分切人",
                self.CONF_SUPPORT_ULTIMATE_PREEMPTION: "开=辅助 Q 待铺时在环合前抢占; 关=仅按普通评分参与切人",
                self.CONF_GROUP_COAXIS: "安魂曲主C与残虹主C的合轴触发键和时序",
                self.CONF_COAXIS_COMBAT_ENABLE: "开=两个主C模板同队时自动进入实战合轴; 关=仅保留按键测试",
                self.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT: (
                    "开=普通入场保持角色原顺序立即执行, 环合入场1s后由planner提前推进原入场流程; "
                    "不会把E后Q角色强制改成Q后E; "
                    "关=保持RU的切人和环合普攻逻辑"
                ),
                self.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT: (
                    "关闭=不固定切人; 1~4=安魂曲真技能确认后严格切到对应队伍位置; "
                    "选残虹主C时保留其Q后合轴, 真技能窗口内不切回安魂曲"
                ),
                self.CONF_COAXIS_TRIGGER_KEY: "按一下开始重复合轴测试, 再按一下停止; 默认8",
                self.CONF_COAXIS_REQUIEM_SWITCH_KEY: "安魂曲在队伍中的数字切换键; 默认1",
                self.CONF_COAXIS_ZANKOU_SWITCH_KEY: "残虹在队伍中的数字切换键; 默认2",
                self.CONF_COAXIS_REQUIEM_DURATION: "安魂曲持续普攻这么久后切到残虹",
                self.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: (
                    "实战合轴中, 安魂曲释放免费技能后按0.1秒间隔普攻这么久; "
                    "辅助大招待开时正常切辅助, 否则请求切残虹"
                ),
                self.CONF_COAXIS_ZANKOU_SWITCH_DELAY: "仅按键测试: 按下残虹切换键后等待这么久再长按普攻; 实战由切人识别和环合结算",
                self.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION: (
                    "实战合轴中, 残虹通过环合切入后静默等待这么久, "
                    "不进行普攻输入, 再从重击开始; 默认1.5s"
                ),
                self.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: (
                    "开=合轴中识别到残虹黄色强化E时中断当前动作, "
                    "成功释放后请求切人; 关=忽略强化E"
                ),
                self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: (
                    "开=开局先切残虹释放黄色强化E, 随后立刻切往原开局目标; "
                    "若残虹本就是开局目标, 则由planner选择其他角色; "
                    "关=不插入该步骤"
                ),
                self.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS: (
                    "开=Boss和小怪战斗都插入黄E入场; 关=仅屏幕顶部有Boss血条时插入"
                ),
                self.CONF_COAXIS_ZANKOU_HOLD_DURATION: "残虹合轴阶段长按普攻的持续秒数",
                self.CONF_COAXIS_ZANKOU_NORMAL_DURATION: "残虹长按结束后按共享间隔持续普攻这么久, 然后切回安魂曲",
                self.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: (
                    "仅残虹完美闪避使用: 从完美闪避声音开始计时, 只点2次普攻, "
                    "剩余时间等待, 然后从重击重新开始"
                ),
                self.CONF_ORDINARY_DODGE_WAIT: (
                    "除安魂曲主C外的角色通用: 从程序首次按Shift开始等待完美闪避声音; "
                    "超时判为普通闪避, 不补普攻并恢复角色原输出"
                ),
                self.CONF_REQUIEM_ORDINARY_DODGE_WAIT: (
                    "仅安魂曲主C使用: 从程序首次按Shift开始等待完美闪避声音; "
                    "超时判为普通闪避, 等待期间不攻击; 合轴时恢复纯普攻, 非合轴时接combo"
                ),
                self.CONF_GROUP_TUNING: "combo轮数/技能前平A/脱战复查/让路/G技能",
                self.CONF_GROUP_TEST: "手动按键总开关, 闪避反击测试/禁用技能大招/模拟闪避",
                self.CONF_MANUAL_KEY_TRIGGERS: (
                    "开=允许鼠标侧键4A, 合轴及所有手动测试按键; "
                    "关=统一忽略这些手动按键"
                ),
            }
        )
        self.name = "安魂曲配置"
        configure_activity(self)  # [lw] Independent top-level activity group.
        # 配置档位组放在最后(活动配置之后)。
        self.default_config.update({self.CONF_GROUP_PRESET: False, self.CONF_PRESET_SLOT: "1"})
        self.config_type.update(
            {
                self.CONF_GROUP_PRESET: config_group([
                    self.CONF_PRESET_SLOT, self.CONF_PRESET_OPS, self.CONF_PRESET_FILE,
                ]),
                self.CONF_PRESET_SLOT: {
                    "type": "drop_down",
                    "options": ["1", "2", "3", "4"],
                },
                self.CONF_PRESET_OPS: {
                    "buttons": [
                        {"text": "保存到该档位", "callback": self._preset_save},
                        {"text": "载入该档位", "callback": self._preset_load},
                    ],
                },
                self.CONF_PRESET_FILE: {
                    "buttons": [
                        {"text": "导出到文件", "callback": self._preset_export},
                        {"text": "从文件导入", "callback": self._preset_import},
                    ],
                },
            }
        )
        self.config_description.update(
            {
                self.CONF_GROUP_PRESET: "保存/载入 1~4 号配置档位, 或导出/导入配置文件",
                self.CONF_PRESET_SLOT: "选择配置档位(1~4), 存取/导入导出都对该档位",
                self.CONF_PRESET_OPS: "保存=当前配置存到该档位; 载入=把该档位配置读回界面",
                self.CONF_PRESET_FILE: "导出=当前配置存成json; 从文件导入=读json回界面",
            }
        )
        self._activity = ActivityController(self)  # [lw]
        self.description = "安魂曲光速4a宏 / 实战闪双4a等配置; 含闪避反击测试开关"
        self._submitted = False
        self._key_was_down = False
        self._macro_running = False
        self._toggle_mode = False   # 本轮是否"按一下开关循环"
        self._toggle_stop = False   # toggle 循环收到停止(再按一下)
        self._tk_was_down = False   # toggle 里检测"再按一下"边沿用的键前态
        self._last_seen_dodge = None  # 闪避反击测试: 上次已处理的声音闪避时刻
        self._in_dodge_test = False   # 正在跑闪避反击测试序列(此时 combo 跑满, 不看触发键)
        self._manual_key_triggers_armed = False
        self._dtk_was_down = False    # 闪避反击模拟测试键(7)的前态(边沿检测)
        self._fbk_was_down = False    # 免费技能后接combo测试键的前态(边沿检测)
        self._coaxis_key_was_down = False  # [lw] Pair-axis toggle edge state.
        self._coaxis_running = False       # [lw] Standalone axis test state.
        self._itx = None     # 框架 interaction, _prepare_input 时取
        self._click_pos = 0  # 点击坐标(屏幕中心)的 lParam, _prepare_input 时算

    def load_config(self):
        """首次改名时沿用旧类名对应的用户配置，已有新配置时不覆盖。"""
        folder = Config.config_folder
        legacy_file = get_relative_path(folder, f"{self.LEGACY_CONFIG_NAME}.json")
        current_file = get_relative_path(folder, f"{self.__class__.__name__}.json")
        if not os.path.exists(current_file) and os.path.isfile(legacy_file):
            try:
                shutil.copyfile(legacy_file, current_file)
                self.logger.info("migrated legacy Requiem config to the renamed task")
            except OSError as e:
                self.logger.warning(
                    f"failed to migrate legacy Requiem config ({type(e).__name__})"
                )
        super().load_config()

    def run(self):
        if not self._submitted:
            if not hasattr(self._activity, "_pause_observer"):  # [lw] Bind once per task.
                self._activity.install_pause_diagnostics()
            self._submitted = True
            self.submit_periodic_task(self.CHECK_INTERVAL, self._loop)
        # [lw] Vision/input runs on the executor, not against its trigger scheduler.
        if self._activity.running:
            self._activity.process()
            return self._activity.running

    def _loop(self):
        if not self.enabled:
            self._activity.stop()  # [lw]
            self._submitted = False
            self._manual_key_triggers_armed = False
            self._reset_manual_key_trigger_state()
            self._macro_running = False
            self._last_seen_dodge = None
            self._coaxis_running = False
            return False

        if self._activity.poll():  # [lw] Activity has its own enable switch.
            return True
        if self._poll_manual_key_triggers():
            return True

        # 闪避反击测试模式: 专门等声音闪避, 触发后执行[双4a→尾段跳A→补平A→N轮combo]。忽略触发键宏。
        if self.config.get(self.CONF_DODGE_TEST):
            self._poll_dodge_counter_test()
            return True
        self._last_seen_dodge = None  # 非测试模式复位, 下次开启重新同步基线

        return True

    def _manual_key_triggers_enabled(self):
        return bool(self.config.get(self.CONF_MANUAL_KEY_TRIGGERS, False))

    def _poll_manual_key_triggers(self):
        """Run every manual test-key listener from one guarded entry point."""

        if not self._manual_key_triggers_enabled():
            self._manual_key_triggers_armed = False
            self._reset_manual_key_trigger_state()
            return False
        if not self._manual_key_triggers_armed:
            self._arm_manual_key_triggers()
            return False
        # Add every new hand-operated test key listener here so the master switch guards it.
        for poller in (
            self._poll_coaxis_trigger,
            self._poll_dodge_test_trigger,
            self._poll_free_skill_combo_test_trigger,
            self._poll_macro_trigger,
        ):
            if poller():
                return True
        return False

    def _reset_manual_key_trigger_state(self):
        self._key_was_down = False
        self._tk_was_down = False
        self._toggle_stop = False
        self._dtk_was_down = False
        self._fbk_was_down = False
        self._coaxis_key_was_down = False

    def _arm_manual_key_triggers(self):
        self._key_was_down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        self._tk_was_down = self._key_was_down
        self._dtk_was_down = self._is_key_pressed(self.config.get(self.CONF_DODGE_TEST_KEY))
        self._fbk_was_down = self._is_key_pressed(self.config.get(self.CONF_FREE_BREAK_TEST_KEY))
        self._coaxis_key_was_down = self._is_key_pressed(
            self.config.get(self.CONF_COAXIS_TRIGGER_KEY)
        )
        self._manual_key_triggers_armed = True

    def _poll_dodge_test_trigger(self):
        """Run the simulated sound-dodge test only on its configured press edge."""

        key = self.config.get(self.CONF_DODGE_TEST_KEY)
        if not key:
            self._dtk_was_down = False
            return False
        key_down = self._is_key_pressed(key)
        edge = key_down and not self._dtk_was_down
        self._dtk_was_down = key_down
        if edge and not self._macro_running:
            self._run_dodge_counter_test(initial_dodge=True)
            return True
        return False

    def _poll_free_skill_combo_test_trigger(self):
        """Run the free-skill combo test only on its configured press edge."""

        key = self.config.get(self.CONF_FREE_BREAK_TEST_KEY)
        if self._same_key(key, self.config.get(self.CONF_COAXIS_TRIGGER_KEY)):
            key = None
        if not key:
            self._fbk_was_down = False
            return False
        key_down = self._is_key_pressed(key)
        edge = key_down and not self._fbk_was_down
        self._fbk_was_down = key_down
        if edge and not self._macro_running:
            self._run_free_skill_combo_test()
            return True
        return False

    def _poll_macro_trigger(self):
        """Run the 4A macro from the shared manual-key listener."""

        if self.config.get(self.CONF_DODGE_TEST):
            return False

        key_down = self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        toggle = self.config.get(self.CONF_TRIGGER_MODE) == self.TRIGGER_TOGGLE
        if toggle:
            edge = key_down and not self._key_was_down
            self._key_was_down = key_down
            if edge and not self._macro_running:
                self._run_macro()
                return True
            return self._macro_running

        if not key_down:
            self._key_was_down = False
            return False
        if self._key_was_down or self._macro_running:
            return self._macro_running
        self._key_was_down = True
        self._run_macro()
        return True

    @staticmethod
    def _same_key(first, second):
        return bool(
            str(first or "").strip()
            and str(first or "").strip().casefold() == str(second or "").strip().casefold()
        )

    def _poll_coaxis_trigger(self):
        """[lw] Start the standalone coordinated-axis loop on a trigger-key edge."""

        key = self.config.get(self.CONF_COAXIS_TRIGGER_KEY)
        if not key:
            self._coaxis_key_was_down = False
            return False
        key_down = self._is_key_pressed(key)
        edge = key_down and not self._coaxis_key_was_down
        self._coaxis_key_was_down = key_down
        if not edge:
            return False
        if self._macro_running:
            return False
        return self._run_coaxis_test()

    def _run_coaxis_test(self):
        """[lw] Run the input-only tester; no combat planner or character state is used."""

        requiem_switch_key = str(
            self.config.get(self.CONF_COAXIS_REQUIEM_SWITCH_KEY, "1")
        ).strip() or "1"
        zankou_switch_key = str(
            self.config.get(self.CONF_COAXIS_ZANKOU_SWITCH_KEY, "2")
        ).strip() or "2"
        settings = CoordinatedAxisSettings(
            trigger_key=str(self.config.get(self.CONF_COAXIS_TRIGGER_KEY, "8")),
            requiem_switch_key=requiem_switch_key,
            zankou_switch_key=zankou_switch_key,
            requiem_attack_duration=max(
                0.0,
                self._conf_num(self.CONF_COAXIS_REQUIEM_DURATION, 2.0),
            ),
            zankou_switch_delay=max(
                0.0,
                self._conf_num(self.CONF_COAXIS_ZANKOU_SWITCH_DELAY, 0.5),
            ),
            zankou_hold_duration=max(
                0.0,
                self._conf_num(self.CONF_COAXIS_ZANKOU_HOLD_DURATION, 2.0),
            ),
            zankou_normal_attack_duration=max(
                0.0,
                self._conf_num(self.CONF_COAXIS_ZANKOU_NORMAL_DURATION, 2.0),
            ),
        )
        self._prepare_input()
        self._macro_running = True
        self._coaxis_running = True
        try:
            RequiemZankouAxisTester(_CoaxisIO(self), settings).run()
            return True
        finally:
            self._mouse_up()
            self._coaxis_running = False
            self._macro_running = False
            self._coaxis_key_was_down = self._is_key_pressed(settings.trigger_key)

    def _coaxis_send_key(self, key):
        """[lw] Send a configured switch key through the framework interaction."""

        self._itx.send_key_down(key)
        try:
            time.sleep(0.02)
        finally:
            self._itx.send_key_up(key)
        return True

    def _conf_num(self, key, default):
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    # ---- 配置档位: 界面内保存/载入 1~4 套 + 导出/从文件导入 ----
    def _preset_keys(self):
        """参与存取的配置键: 除下划线内部键, "档位选择器"本身和折叠分组展开状态外的全部。"""
        excluded = {self.CONF_PRESET_SLOT} | config_group_keys(self.config_type)
        return [k for k in self.default_config
                if not k.startswith("_") and k not in excluded]

    def _current_slot(self):
        return str(self.config.get(self.CONF_PRESET_SLOT, "1"))

    def _read_presets(self):
        import json
        import os
        try:
            if os.path.exists(self.PRESET_FILE):
                with open(self.PRESET_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log_error(f"读取档位文件失败: {e}")
        return {}

    def _write_presets(self, data):
        import json
        try:
            with open(self.PRESET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_error(f"写档位文件失败: {e}")

    def _apply_values(self, values):
        """把一份配置值套回当前配置(只认已知键), 并刷新界面。返回套用的项数。"""
        if not isinstance(values, dict):
            return 0
        n = 0
        for k in self._preset_keys():
            if k in values and values[k] is not None:
                self.config[k] = values[k]
                n += 1
        self._refresh_config_ui()
        return n

    def _refresh_config_ui(self):
        """载入后让界面控件重新读配置(含子配置显隐)。拿不到界面就静默跳过(如无GUI)。"""
        try:
            from ok import og
            tab = getattr(getattr(og, "main_window", None), "trigger_tab", None)
            for card in getattr(tab, "card_widgets", []) or []:
                if getattr(card, "task", None) is self:
                    card.update_config()
                    break
        except Exception as e:
            self.log_error(f"刷新配置界面失败: {e}")

    def _preset_save(self, *args):
        slot = self._current_slot()
        data = self._read_presets()
        data[slot] = {k: self.config.get(k) for k in self._preset_keys()}
        self._write_presets(data)
        self.log_info(f"已保存当前配置到档位 {slot}", notify=True)

    def _preset_load(self, *args):
        slot = self._current_slot()
        values = self._read_presets().get(slot)
        if not values:
            self.log_info(f"档位 {slot} 还没保存过配置", notify=True)
            return
        n = self._apply_values(values)
        self.log_info(f"已载入档位 {slot} 的配置({n}项)", notify=True)

    def _preset_exchange_directory(self):
        path = get_relative_path(self.EXCHANGE_DIRECTORY)
        os.makedirs(path, exist_ok=True)
        return path

    def _preset_export_default_path(self):
        return os.path.join(self._preset_exchange_directory(), self.EXCHANGE_FILE_NAME)

    def _preset_export(self, *args):
        import json
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            None,
            "导出安魂曲配置",
            self._preset_export_default_path(),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({k: self.config.get(k) for k in self._preset_keys()},
                          f, ensure_ascii=False, indent=2)
            self.log_info(f"已导出到 {path}", notify=True)
        except Exception as e:
            self.log_error(f"导出失败: {e}")

    def _preset_import(self, *args):
        import json
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None,
            "从文件导入安魂曲配置",
            self._preset_exchange_directory(),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                values = json.load(f)
            n = self._apply_values(values)
            self.log_info(f"已从 {path} 导入 {n} 项", notify=True)
        except Exception as e:
            self.log_error(f"导入失败: {e}")

    def _scheme_d4_params(self):
        """双4a(声音闪避版)时序从配置读: 前段平A/跳A按住/后段平A + 前后共用的连点按下/抬起。"""
        return dict(
            front_ms=self._conf_num(self.CONF_D4_FRONT, 950),
            jump_hold_ms=self._conf_num(self.CONF_D4_JUMP_HOLD, 40),
            back_ms=self._conf_num(self.CONF_D4_BACK, 200),
            click=(self._conf_num(self.CONF_D4_CLICK_HOLD, 40),
                   self._conf_num(self.CONF_D4_CLICK_GAP, 8)),
        )

    def _scheme_ls_params(self):
        """方案四(光速4a·时间驱动)时序从配置读: 连点节拍 + 跳A时机/按住 + 收尾。"""
        return dict(
            click=(self._conf_num(self.CONF_LS_CLICK_HOLD, 40),
                   self._conf_num(self.CONF_LS_CLICK_GAP, 8)),
            jump_at_ms=self._conf_num(self.CONF_LS_JUMP_AT, 1470),
            jump_hold_ms=self._conf_num(self.CONF_LS_JUMP_HOLD, 18),
            jump_tail_ms=self._conf_num(self.CONF_LS_TAIL, 218),
        )

    def scheme_round_seconds(self):
        """光速4a一轮 combo 的预计时长(秒), 按配置的跳A时机+按住+收尾算; 供实战估 combo 进度。"""
        p = self._scheme_ls_params()
        return (p["jump_at_ms"] + p["jump_hold_ms"] + p["jump_tail_ms"]) / 1000.0

    def run_combo_once(self, io):
        """按配置跑一轮光速4a combo(宏/测试/实战主C共用)。"""
        requiem_combo.run_scheme_lightspeed(io, **self._scheme_ls_params())

    def _run_combo_rounds(self, io, rounds):
        for _ in range(rounds):
            self.run_combo_once(io)

    def _run_macro(self):
        self._macro_running = True
        self._toggle_mode = self.config.get(self.CONF_TRIGGER_MODE) == self.TRIGGER_TOGGLE
        self.log_info(f"requiem jump attack macro start toggle={self._toggle_mode}")
        start = time.perf_counter()
        # 提高系统定时器精度到1ms, 否则 time.sleep 的几十ms被Windows默认~15ms粒度取整, 打乱连招节奏。
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self._prepare_input()
            io = _MacroIO(self)
            loop = self._run_scheme_loop_toggle if self._toggle_mode else self._run_scheme_loop
            loop(lambda: self.run_combo_once(io), "光速4a")
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            elapsed = time.perf_counter() - start
            self.log_info(f"requiem jump attack macro end elapsed={elapsed:.3f}s")
            self._macro_running = False

    def _macro_should_continue(self):
        """方案执行器每一下之前查: 测试序列=跑满一整轮(不打断); toggle=没收到"再按一下"; 长按=键还按着。"""
        if self._in_dodge_test:
            return True
        if self._toggle_mode:
            return self._manual_key_triggers_enabled() and not self._check_toggle_stop()
        return self._trigger_held()

    def _poll_dodge_counter_test(self):
        """闪避反击测试: 轮询声音闪避时刻, 检测到新的一次就完整跑一轮测试序列(中途不打断)。
        跑完后把这一轮期间发生的所有闪避都消费掉(不堆积), 只对本轮结束后的新闪避再触发下一轮。
        首次(开启后)只同步基线, 不对开启前的旧闪避触发。"""
        from src.sound_trigger.SoundCombatContext import SoundCombatContext

        now_dodge = SoundCombatContext().last_dodge_time()
        if self._last_seen_dodge is None:
            self._last_seen_dodge = now_dodge
            return
        if now_dodge > self._last_seen_dodge and not self._macro_running:
            self._run_dodge_counter_test()
            # 消费掉这一轮期间(怪一直攻击会攒很多)的所有闪避: 只对本轮结束后的新闪避再触发下一轮。
            self._last_seen_dodge = SoundCombatContext().last_dodge_time()

    def _run_dodge_counter_test(self, initial_dodge=False):
        """一次完整测试序列(和实战闪双4a同一份配置, 中途不打断): [可选:模拟初始闪避] → 双4a(前段平A →
        跳A → 后段平A) → 尾段跳A → 补平A → combo轮数 轮光速4a。全实时读配置。整轮期间暂停声音自动
        闪避, 免得 SoundTriggerTask 对真·敌人攻击的闪避插进来把这一轮搅乱(只暂停这一小段, 实战不受影响)。
        initial_dodge=True(按7模拟声音): 先自己按一下 shift 当作声音触发的那次初始闪避。"""
        from src.sound_trigger.SoundCombatContext import SoundCombatContext

        self._macro_running = True
        self._in_dodge_test = True
        SoundCombatContext.set_dodge_paused(True)  # 整轮期间暂停声音自动闪避, 让流程干净可观察
        rounds = max(0, int(self._conf_num(self.CONF_COMBO_ROUNDS, self.DODGE_TEST_COMBO_ROUNDS)))
        self.log_info("闪避反击测试: 触发")
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self._prepare_input()
            io = _MacroIO(self)
            if initial_dodge:
                self.send_key(self.DODGE_KEY, down_time=0.02)  # 模拟声音触发的初始闪避
                time.sleep(0.1)
            p = self._scheme_d4_params()
            requiem_combo.run_scheme_double_4a(io, **p)
            # 尾段: 跳A(空格+左键同按, 复用光速4a的跳A按住)代替闪避
            jh = self._conf_num(self.CONF_LS_JUMP_HOLD, 18)
            io.space_down()
            io.mouse_down()
            io.sleep_ms(jh)
            io.mouse_up()
            io.space_up()
            # 跳A后补平A: 时长可配, 平A节拍复用光速4a连点按住/抬起
            fill = self._conf_num(self.CONF_D4_TAIL_FILL, 350)
            requiem_combo._fill_attacks(io, fill,
                                        self._conf_num(self.CONF_LS_CLICK_HOLD, 40),
                                        self._conf_num(self.CONF_LS_CLICK_GAP, 8))
            self._run_combo_rounds(io, rounds)
            self.log_info(
                f"闪避反击测试(双4a): 前段{p['front_ms']}→跳A{p['jump_hold_ms']}→后段{p['back_ms']}ms "
                f"→ 跳+左键{jh:.0f}ms → 补平A{fill:.0f}ms → 光速4a×{rounds}")
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            SoundCombatContext.set_dodge_paused(False)  # 恢复声音自动闪避
            self._in_dodge_test = False
            self._macro_running = False
            self.log_info("闪避反击测试: 一次序列完成")

    def _run_free_skill_combo_test(self):
        """免费技能后接combo测试: 发技能键放(免费)技能 → delay → 闪避打断拖沓低伤的a5 → wait → combo。
        需在游戏里把技能设成免费技能(可反复放, 不受16s真技能CD限制)。期间暂停声音自动闪避, 便于反复调
        delay/hold。时序与实战侧(Requiem._free_skill_break_a5)同一份配置。"""
        from src.sound_trigger.SoundCombatContext import SoundCombatContext

        self._macro_running = True
        self._in_dodge_test = True
        SoundCombatContext.set_dodge_paused(True)
        delay = self._conf_num(self.CONF_FREE_BREAK_DELAY, 200)
        hold = self._conf_num(self.CONF_FREE_BREAK_JUMP_HOLD, 20)
        wait = self._conf_num(self.CONF_FREE_BREAK_WAIT, 0)
        skill_key = self.config.get(self.CONF_FREE_SKILL_KEY, "e")
        self.log_info(f"免费技能后接combo测试: 触发 (技能键={skill_key})")
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self._prepare_input()
            io = _MacroIO(self)
            if skill_key:
                self.send_key(str(skill_key), down_time=0.02)  # 放(免费)技能
            if delay > 0:
                time.sleep(delay / 1000.0)
            self.send_key_down(self.DODGE_KEY)   # 闪避打断a5
            io.sleep_ms(hold)
            self.send_key_up(self.DODGE_KEY)
            if wait > 0:
                io.sleep_ms(wait)
            rounds = max(1, int(self._conf_num(self.CONF_COMBO_ROUNDS, self.DODGE_TEST_COMBO_ROUNDS)))
            self._run_combo_rounds(io, rounds)   # 打断后接光速4a, 轮数复用"combo轮数"
            self.log_info(
                f"免费技能后接combo测试: 放技能→等{delay:.0f}→闪避{hold:.0f}→等{wait:.0f}ms → {rounds}轮光速4a")
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            SoundCombatContext.set_dodge_paused(False)
            self._in_dodge_test = False
            self._macro_running = False

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
        while (
            self._manual_key_triggers_enabled()
            and self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        ):
            time.sleep(0.02)
        self._tk_was_down = False
        self._toggle_stop = False
        rounds = 0
        while self.enabled and self._manual_key_triggers_enabled() and not self._toggle_stop:
            run_once()
            rounds += 1
            if self._check_toggle_stop():
                break
            time.sleep(self.SCHEME_LOOP_GAP)
        self.log_info(f"requiem {name} toggle loop end rounds={rounds}")

    # ---------- 光速4a宏(框架输入, 长按循环, 松手即停) ----------
    def _trigger_held(self):
        """触发键是否仍被按住(且任务仍启用)。松手/停用即返回 False → 中止当前宏。"""
        return (
            self.enabled
            and self._manual_key_triggers_enabled()
            and self._is_key_pressed(self.config.get(self.CONF_TRIGGER_KEY))
        )

    def _prepare_input(self):
        """取框架 interaction(和自动战斗同一路输入), 预取一次点击坐标(屏幕中心)的 lParam。"""
        self._itx = self.executor.interaction
        try:
            cx = round(self._itx.capture.width * 0.5)
            cy = round(self._itx.capture.height * 0.5)
            self._click_pos = self._itx.update_mouse_pos(cx, cy)
        except Exception as e:
            self.log_info(f"input prepare pos failed, fallback center: {e}")
            self._click_pos = self._itx.update_mouse_pos(-1, -1)

    def _mouse_down(self):
        self._itx.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, self._click_pos)

    def _mouse_up(self):
        self._itx.post(win32con.WM_LBUTTONUP, 0, self._click_pos)

    def _space_down(self):
        self._itx.send_key_down("space")

    def _space_up(self):
        self._itx.send_key_up("space")

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
