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
    MODE_SCHEME_LS = "光速4a(方案四·时间驱动)"  # 方案一进化: 连点到"跳A时机"才跳, 改时机时跳A左键自动跟着走
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
    # 安魂曲实战: 真技能前先起手平A进入交战这么久(防开战瞬间直接放技能打空); 0=不补。
    # 原在"自动战斗"界面, 挪来这里统一; 实战侧(Requiem)读这个值。
    CONF_ENGAGE_ATTACK = "安魂曲技能前平A(s)"
    # 当前流程(方案一)的主动闪避次数: 1=现状(闪避后连段停在a4, combo可能错位);
    # 2=连续两次闪避重置连段→后续combo从a1起手对齐。间隔=两次闪避之间的等待(给闪避后摇)。
    CONF_DODGE_COUNT = "主动闪避次数"
    CONF_DODGE_GAP = "主动闪避间隔(s)"
    # 闪避反击测试开关: 打开后本任务专门测这套时序 —— 关掉自动战斗、开这个, 每次声音闪避触发就
    # 执行[闪避反击强制平A(CONF_DODGE_COUNTER) → combo前后摇等待(CONF_DODGE_COMBO_WAIT) → 2轮combo],
    # 方便边看边调那两个 0.3s。开启时忽略触发键宏, 只等声音闪避。
    CONF_DODGE_TEST = "闪避反击测试开关"  # 布尔开关(SwitchButton); 改过名, 让旧的下拉字符串值作废
    # 实战测试开关: 开=安魂曲只站场打 combo、不放技能/大招, 方便单独测 combo 手感 + 闪避。实战读它。
    CONF_DISABLE_SKILLS = "禁用技能大招(测试)"  # 布尔开关
    DODGE_TEST_COMBO_ROUNDS = 2  # 测试里反击后接几轮 combo 的默认值(配置读不到时用)
    CONF_COMBO_ROUNDS = "combo轮数"  # 测试里反击+闪避之后接几轮 combo, 可配
    # 闪避反击测试用哪套流程(供对比):
    #   当前: 强制平A(反击/第一个4a) → 主动闪避(再触发一个4a) → 后摇等待 → N轮方案一combo。
    #   闪双4a: 闪避后等后摇 → 直接打方案二(5点4a → 跳A取消续打 → …), 用跳A取消续打第二个4a,
    #          不用主动闪避、不重起combo(参考"闪后双4a"原设计)。
    CONF_DODGE_STYLE = "闪避反击方式"
    STYLE_CURRENT = "反击+主动闪避+方案一"
    STYLE_SCHEME_B = "闪双4a(方案二)"
    # 双4a(声音闪避版)的可调时序(选"闪双4a"才显示): 声音闪避后 → 前段平A(打第一个4a) → 跳A(空格+
    # 左键同按)代替第二次闪避、续段 → 后段平A(接第二个4a)。三段时长各自可配, 前后平A共用连点按下/抬起
    # (逻辑同光速4a方案四)。精确时序在 requiem_combo.run_scheme_double_4a。
    CONF_D4_FRONT = "双4a-前段平A(ms)"       # 第一个4a: 跳A之前的平A时长
    CONF_D4_JUMP_HOLD = "双4a-跳A按住(ms)"    # 空格+左键同时按住(代替闪避)
    CONF_D4_BACK = "双4a-后段平A(ms)"        # 第二个4a: 跳A之后的平A时长
    CONF_D4_CLICK_HOLD = "双4a-连点按住(ms)"  # 前后两段平A共用的左键按住
    CONF_D4_CLICK_GAP = "双4a-连点抬起(ms)"   # 前后两段平A共用的左键抬起
    # 双4a尾段(两个4a打完后)的"闪避替代"方式 + 闪避后补平A(替换旧的死等延迟)。
    CONF_D4_TAIL_DODGE = "双4a-尾段闪避方式"   # drop_down: W+闪避 / 跳+左键(复用光速4a跳A按住)
    D4_DODGE_W = "W+闪避"                     # 按住W再按闪避(带前冲方向)
    D4_DODGE_JUMP = "跳+左键(光速4a跳A)"       # 空格+左键同按, 时长复用光速4a的"跳A按住"
    CONF_D4_TAIL_FILL = "双4a-闪避后补平A(ms)"  # 替换延迟: 闪避后补平A的时长(平A节拍复用光速4a连点按住/抬起)
    DODGE_KEY = "lshift"  # 游戏闪避键(主动闪避/闪避测试用)
    DODGE_DIR_KEY = "w"   # 双4a尾段闪避的方向键: 按住W再按闪避(带前冲方向), 再一起松
    # 专测"闪避后接第一个平A所需时间"的触发键: 按一下→闪避→等 combo前后摇等待→打一个平A。
    # 用来调 combo前后摇等待(=闪避后到首平A的时间)。留空=关闭。
    CONF_FIRST_ATTACK_TEST_KEY = "闪避后首平A测试键"
    # 模拟声音闪避的测试键: 按一下=假装出现了声音闪避, 走一整轮完整流程[初始闪避→强制平A→主动闪避
    # →后摇→N轮combo], 整轮暂停声音自动闪避。不用真声音、不受敌人干扰, 最适合看清流程。留空=关闭。
    CONF_DODGE_TEST_KEY = "闪避反击模拟测试键"

    # 方案四(光速4a·时间驱动)的可调时序, 单位毫秒(默认见 requiem_combo.SCHEME_LS_*)。
    # 核心是"跳A时机": 连点累计到这个时刻才左键+空格同跳, 改它时跳A那下左键自动跟着移动。
    # 同样用开关折叠, 默认收起。
    CONF_LS_EXPAND = "方案四-展开时序配置"  # 布尔开关(SwitchButton), 开=展开5个配置
    CONF_LS_JUMP_AT = "方案四-跳A时机(ms)"
    CONF_LS_JUMP_HOLD = "方案四-跳A按住(ms)"
    CONF_LS_CLICK_HOLD = "方案四-连点按住(ms)"
    CONF_LS_CLICK_GAP = "方案四-连点抬起(ms)"
    CONF_LS_TAIL = "方案四-跳后收尾(ms)"

    # 配置档位: 界面内保存/载入 1~4 套配置(存在 PRESET_FILE), 外加导出/从文件导入。
    CONF_PRESET_SLOT = "配置档位"       # drop_down 1/2/3/4
    CONF_PRESET_OPS = "档位存取"        # 两个按钮: 保存到该档位 / 载入该档位
    CONF_PRESET_FILE = "配置文件"       # 两个按钮: 导出到文件 / 从文件导入
    PRESET_FILE = "configs/RequiemPresets.json"  # 4 套档位存这里

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
                # 默认值 = longwei 实测调优后的最优解(2026-07-05)。别的机器哪怕微调, 也从这套起,
                # 而不是最初那套(如光速4a跳A时机1470根本触发不了)。
                self.CONF_TRIGGER_KEY: "mouse5",
                self.CONF_MACRO_MODE: self.MODE_SCHEME_LS,
                self.CONF_TRIGGER_MODE: self.TRIGGER_HOLD,
                self.CONF_INPUT_MODE: self.INPUT_BG,
                self.CONF_DODGE_COUNTER: 0.95,
                self.CONF_DODGE_COMBO_WAIT: 0.6,
                self.CONF_DODGE_COUNT: 1,
                self.CONF_DODGE_GAP: 0.3,
                self.CONF_COMBO_ROUNDS: 2,
                self.CONF_ENGAGE_ATTACK: 0.15,
                self.CONF_DODGE_TEST: False,
                self.CONF_DISABLE_SKILLS: False,
                self.CONF_DODGE_STYLE: self.STYLE_SCHEME_B,
                self.CONF_D4_FRONT: 1950,
                self.CONF_D4_JUMP_HOLD: 20,
                self.CONF_D4_BACK: 700,
                self.CONF_D4_CLICK_HOLD: 20,
                self.CONF_D4_CLICK_GAP: 20,
                self.CONF_D4_TAIL_DODGE: self.D4_DODGE_JUMP,
                self.CONF_D4_TAIL_FILL: 250,
                self.CONF_FIRST_ATTACK_TEST_KEY: "6",
                self.CONF_DODGE_TEST_KEY: "7",
                self.CONF_LS_EXPAND: True,
                self.CONF_LS_JUMP_AT: 1800,
                self.CONF_LS_JUMP_HOLD: 20,
                self.CONF_LS_CLICK_HOLD: 20,
                self.CONF_LS_CLICK_GAP: 20,
                self.CONF_LS_TAIL: 200,
                self.CONF_PRESET_SLOT: "1",
            }
        )
        self.config_type.update(
            {
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
                self.CONF_MACRO_MODE: {
                    "type": "drop_down",
                    "options": [self.MODE_RECORDED, self.MODE_SCHEME_A, self.MODE_SCHEME_LS],
                },
                # 方案四那5个时序配置用开关按钮折叠, 打开(True)才显示。
                self.CONF_LS_EXPAND: {
                    "sub_configs": {
                        True: [
                            self.CONF_LS_JUMP_AT, self.CONF_LS_JUMP_HOLD,
                            self.CONF_LS_CLICK_HOLD, self.CONF_LS_CLICK_GAP,
                            self.CONF_LS_TAIL,
                        ],
                    },
                },
                self.CONF_TRIGGER_MODE: {
                    "type": "drop_down",
                    "options": [self.TRIGGER_HOLD, self.TRIGGER_TOGGLE],
                },
                self.CONF_DODGE_STYLE: {
                    "type": "drop_down",
                    "options": [self.STYLE_CURRENT, self.STYLE_SCHEME_B],
                    # 选"闪双4a"才显示它那5个专属时序。
                    "sub_configs": {self.STYLE_SCHEME_B: [
                        self.CONF_D4_FRONT, self.CONF_D4_JUMP_HOLD, self.CONF_D4_BACK,
                        self.CONF_D4_CLICK_HOLD, self.CONF_D4_CLICK_GAP,
                        self.CONF_D4_TAIL_DODGE, self.CONF_D4_TAIL_FILL,
                    ]},
                },
                self.CONF_D4_TAIL_DODGE: {
                    "type": "drop_down",
                    "options": [self.D4_DODGE_W, self.D4_DODGE_JUMP],
                },
                self.CONF_INPUT_MODE: {
                    "type": "drop_down",
                    "options": [self.INPUT_HW, self.INPUT_BG],
                },
            }
        )
        self.config_description.update(
            {
                self.CONF_TRIGGER_KEY: "长按该键执行4A+跳A宏(松手即停)",
                self.CONF_MACRO_MODE: "4A宏模式: 原始录制/方案一/光速4a(方案四)",
                self.CONF_TRIGGER_MODE: "长按循环(松手停) 或 按一下开/关循环",
                self.CONF_INPUT_MODE: "仅方案一/四: 前台(硬件) 或 后台(发消息)",
                self.CONF_DODGE_COUNTER: "闪避反击强制平A秒数(0.1间隔), 保证反击打出; 0=关",
                self.CONF_DODGE_COMBO_WAIT: "combo前若紧接闪避反击, 额外等这么久走完后摇; 0=不等",
                self.CONF_DODGE_COUNT: "方案一反击后主动闪避几次: 2=重置连段让combo从a1对齐",
                self.CONF_DODGE_GAP: "主动闪避≥2次时, 每两次之间等这么久",
                self.CONF_COMBO_ROUNDS: "反击+闪避后接几轮combo",
                self.CONF_ENGAGE_ATTACK: "放真技能前先平A进交战这么久, 防打空; 0=不补",
                self.CONF_DODGE_TEST: "开=每次声音闪避走一整轮(关自动战斗后调时间用)",
                self.CONF_DISABLE_SKILLS: "开=安魂曲只站场打combo、不放技能/大招(测手感/闪避用); 刷本记得关",
                self.CONF_DODGE_STYLE: "闪避反击方式: 方案一 / 闪双4a",
                self.CONF_D4_FRONT: "双4a 前段平A毫秒(打第一个4a); 太短会接不出第二个4a",
                self.CONF_D4_JUMP_HOLD: "双4a 跳A空格+左键同按毫秒(代替闪避)",
                self.CONF_D4_BACK: "双4a 后段平A毫秒(接第二个4a)",
                self.CONF_D4_CLICK_HOLD: "双4a 前后平A共用的左键按住毫秒",
                self.CONF_D4_CLICK_GAP: "双4a 前后平A共用的左键抬起毫秒",
                self.CONF_D4_TAIL_DODGE: "双4a两个4a后的闪避替代: W+闪避 / 跳+左键(复用光速4a跳A按住)",
                self.CONF_D4_TAIL_FILL: "双4a 闪避后补平A毫秒(替换延迟; 平A节拍复用光速4a连点按住/抬起)",
                self.CONF_FIRST_ATTACK_TEST_KEY: "按此键→闪避→等后摇→打一个平A(调后摇用); 留空=关",
                self.CONF_DODGE_TEST_KEY: "按此键=模拟一次声音闪避走整轮; 留空=关",
                self.CONF_LS_EXPAND: "开=展开方案四(光速4a)5个时序配置(默认收起)",
                self.CONF_LS_JUMP_AT: "方案四 跳A时机毫秒(核心); 大世界约1390其他约1470; 跳早出1a",
                self.CONF_LS_JUMP_HOLD: "方案四 跳A左键+空格同按毫秒(参考18)",
                self.CONF_LS_CLICK_HOLD: "方案四 连点每下左键按住毫秒",
                self.CONF_LS_CLICK_GAP: "方案四 连点每下左键抬起毫秒",
                self.CONF_LS_TAIL: "方案四 跳A后收尾毫秒(连点节拍继续平A填满; 参考218)",
                self.CONF_PRESET_SLOT: "选择配置档位(1~4), 存取/导入导出都对该档位",
                self.CONF_PRESET_OPS: "保存=当前配置存到该档位; 载入=把该档位配置读回界面",
                self.CONF_PRESET_FILE: "导出=当前配置存成json; 从文件导入=读json回界面",
            }
        )
        self.name = "安魂曲配置"
        self.description = "安魂曲4A跳A宏 / 实战闪避反击等配置; 含闪避反击测试开关"
        self._submitted = False
        self._key_was_down = False
        self._macro_running = False
        self._toggle_mode = False   # 本轮是否"按一下开关循环"
        self._toggle_stop = False   # toggle 循环收到停止(再按一下)
        self._tk_was_down = False   # toggle 里检测"再按一下"边沿用的键前态
        self._last_seen_dodge = None  # 闪避反击测试: 上次已处理的声音闪避时刻
        self._in_dodge_test = False   # 正在跑闪避反击测试序列(此时 combo 跑满, 不看触发键)
        self._fk_was_down = False     # 闪避后首平A测试键的前态(边沿检测)
        self._dtk_was_down = False    # 闪避反击模拟测试键(7)的前态(边沿检测)

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
            self._last_seen_dodge = None
            return False

        # 闪避反击模拟测试键(7, 边沿触发): 假装出现声音, 走一整轮完整流程(含初始闪避)。
        dtk = self.config.get(self.CONF_DODGE_TEST_KEY)
        if dtk:
            ddown = self._is_key_pressed(dtk)
            dedge = ddown and not self._dtk_was_down
            self._dtk_was_down = ddown
            if dedge and not self._macro_running:
                self._run_dodge_counter_test(initial_dodge=True)
                return True
        else:
            self._dtk_was_down = False

        # 闪避后首平A测试键(边沿触发): 任何时候都响应(不受闪避反击测试开关影响)。
        # 按一下→闪避→等 combo前后摇等待→打一个平A。
        fk = self.config.get(self.CONF_FIRST_ATTACK_TEST_KEY)
        if fk:
            fdown = self._is_key_pressed(fk)
            fedge = fdown and not self._fk_was_down
            self._fk_was_down = fdown
            if fedge and not self._macro_running:
                self._run_first_attack_test()
                return True
        else:
            self._fk_was_down = False

        # 闪避反击测试模式: 专门等声音闪避, 触发后执行[强制平A→主动闪避→后摇等待→N轮combo]。忽略触发键宏。
        if self.config.get(self.CONF_DODGE_TEST):
            self._poll_dodge_counter_test()
            return True
        self._last_seen_dodge = None  # 非测试模式复位, 下次开启重新同步基线

        # 后台发消息模式(方案一/四)允许游戏不在前台时执行; 其余(硬件/原始录制)仍要求前台。
        bg_mode = (
            self.config.get(self.CONF_MACRO_MODE) in (
                self.MODE_SCHEME_A, self.MODE_SCHEME_LS)
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

    # ---- 配置档位: 界面内保存/载入 1~4 套 + 导出/从文件导入 ----
    def _preset_keys(self):
        """参与存取的配置键: 除下划线内部键和"档位选择器"本身外的全部。"""
        return [k for k in self.default_config
                if not k.startswith("_") and k != self.CONF_PRESET_SLOT]

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

    def _preset_export(self, *args):
        import json
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(None, "导出安魂曲配置", "安魂曲配置.json", "JSON (*.json)")
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
        path, _ = QFileDialog.getOpenFileName(None, "从文件导入安魂曲配置", "", "JSON (*.json)")
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

    def _scheme_runner(self, mode, io):
        """mode → (跑一轮的可调用, 显示名)。方案四的时序由配置实时决定。"""
        if mode == self.MODE_SCHEME_A:
            return (lambda: requiem_combo.run_scheme_a(io)), "安魂曲(方案一)"
        if mode == self.MODE_SCHEME_LS:
            params = self._scheme_ls_params()
            return (lambda: requiem_combo.run_scheme_lightspeed(io, **params)), "光速4a(方案四)"
        return None

    def _directional_dodge(self):
        """带方向的闪避: 像跳A那样两键一起按——先按住W、再按闪避, 稍顿再一起松开闪避和W。
        W给闪避一个前冲方向(不是原地闪)。"""
        self.send_key_down(self.DODGE_DIR_KEY)  # 按住W
        self.send_key_down(self.DODGE_KEY)      # 再按闪避
        time.sleep(0.05)
        self.send_key_up(self.DODGE_KEY)        # 松闪避
        self.send_key_up(self.DODGE_DIR_KEY)    # 松W

    def _run_combo_rounds(self, io, rounds):
        """按"4A宏模式"的当前选择+配置跑 rounds 轮 combo(方案一/二/三/四共用同一处选择);
        原始录制/未知模式回退方案一。返回所用方案的显示名, 便于日志。"""
        mode = self.config.get(self.CONF_MACRO_MODE, self.MODE_SCHEME_A)
        runner = self._scheme_runner(mode, io)
        if runner is None:
            run_once, name = (lambda: requiem_combo.run_scheme_a(io)), "方案一(回退)"
        else:
            run_once, name = runner
        for _ in range(rounds):
            run_once()
        return name

    def _run_macro(self):
        self._macro_running = True
        mode = self.config.get(self.CONF_MACRO_MODE, self.MODE_SCHEME_A)
        self._toggle_mode = self.config.get(self.CONF_TRIGGER_MODE) == self.TRIGGER_TOGGLE
        self.log_info(f"requiem jump attack macro start mode={mode} toggle={self._toggle_mode}")
        start = time.perf_counter()
        # 提高系统定时器精度到1ms, 否则 time.sleep 的几十ms被Windows默认~15ms粒度取整, 打乱连招节奏。
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            if mode in (self.MODE_SCHEME_A, self.MODE_SCHEME_LS):
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
        """方案执行器每一下之前查: 测试序列=跑满一整轮(不打断); toggle=没收到"再按一下"; 长按=键还按着。"""
        if self._in_dodge_test:
            return True
        if self._toggle_mode:
            return not self._check_toggle_stop()
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
        """一次完整测试序列(和实战 on_dodge_counter 同流程, 中途不打断): [可选:模拟初始闪避] →
        强制平A反击 → 主动闪避(按一下shift)取消反击后摇 → 等 combo前后摇等待 → DODGE_TEST_COMBO_ROUNDS
        轮 combo(方案一)。全实时读配置。整轮期间暂停声音自动闪避, 免得 SoundTriggerTask 对真·敌人
        攻击的闪避插进来把这一轮搅乱(只暂停这一小段, 实战不受影响)。
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
            style = self.config.get(self.CONF_DODGE_STYLE, self.STYLE_CURRENT)
            wait = self._conf_num(self.CONF_DODGE_COMBO_WAIT, 0.3)
            if style == self.STYLE_SCHEME_B:
                # 双4a(声音闪避版): 前段平A(打第一个4a) → 跳A(空格+左键同按)代替第二次闪避、续段 →
                # 后段平A(接第二个4a)。两个4a打完后, 接方案一那套尾段: 主动闪避 → 延迟(后摇等待) →
                # combo × rounds。combo 复用"4A宏模式"的选择+配置, 轮数复用"combo轮数"。
                p = self._scheme_d4_params()
                requiem_combo.run_scheme_double_4a(io, **p)
                # 尾段闪避替代: W+闪避 或 跳+左键同按(复用光速4a的跳A按住)
                if self.config.get(self.CONF_D4_TAIL_DODGE, self.D4_DODGE_W) == self.D4_DODGE_JUMP:
                    jh = self._conf_num(self.CONF_LS_JUMP_HOLD, 18)
                    io.space_down()
                    io.mouse_down()
                    io.sleep_ms(jh)
                    io.mouse_up()
                    io.space_up()
                    dodge_name = f"跳+左键{jh:.0f}ms"
                else:
                    self._directional_dodge()                   # 按住W再按闪避
                    dodge_name = "W+闪避"
                # 闪避后补平A(替换旧的死等延迟): 时长可配, 平A节拍复用光速4a连点按住/抬起
                fill = self._conf_num(self.CONF_D4_TAIL_FILL, 350)
                requiem_combo._fill_attacks(io, fill,
                                            self._conf_num(self.CONF_LS_CLICK_HOLD, 40),
                                            self._conf_num(self.CONF_LS_CLICK_GAP, 8))
                name = self._run_combo_rounds(io, rounds)       # combo × rounds(按4A宏模式)
                self.log_info(
                    f"闪避反击测试(双4a): 前段{p['front_ms']}→跳A{p['jump_hold_ms']}→后段{p['back_ms']}ms "
                    f"→ {dodge_name} → 补平A{fill:.0f}ms → {name}×{rounds}")
            else:
                # 当前(方案一): [强制平A(反击, 打出一个高伤4a) → 主动闪避] 重复 N 次(N=主动闪避次数),
                # 每次白嫖一个4a; 最后一次闪避把连段重置 → 后摇等待 → rounds轮方案一combo(从a1起手对齐)。
                dur = self._conf_num(self.CONF_DODGE_COUNTER, 0.3)
                count = max(1, int(self._conf_num(self.CONF_DODGE_COUNT, 1)))
                gap = self._conf_num(self.CONF_DODGE_GAP, 0.3)
                for i in range(count):
                    n = 0
                    start = time.time()
                    while time.time() - start < dur:
                        io.mouse_down()
                        time.sleep(0.015)
                        io.mouse_up()
                        n += 1
                        time.sleep(0.1)
                    self.send_key(self.DODGE_KEY, down_time=0.02)  # 主动闪避(按一下shift)
                    if i < count - 1 and gap > 0:
                        time.sleep(gap)  # 等这个4a打出来再进下一段[强制平A→主动闪避]
                self.log_info(f"闪避反击测试: [强制平A{dur:.2f}s→主动闪避]×{count} → 后摇{wait:.2f}s → {rounds}轮combo")
                if wait > 0:
                    time.sleep(wait)
                for _ in range(rounds):
                    requiem_combo.run_scheme_a(io)
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            SoundCombatContext.set_dodge_paused(False)  # 恢复声音自动闪避
            self._in_dodge_test = False
            self._macro_running = False
            self.log_info("闪避反击测试: 一次序列完成")

    def _run_first_attack_test(self):
        """专测"闪避后接第一个平A所需时间": 闪避(按一下shift) → 等 combo前后摇等待秒 → 打一个平A。
        调 CONF_DODGE_COMBO_WAIT 到刚好能接上平A, 就是实战闪避后到首平A的等待。
        期间暂停声音自动闪避, 免得 SoundTriggerTask 插进来搅乱。"""
        from src.sound_trigger.SoundCombatContext import SoundCombatContext

        self._macro_running = True
        wait = self._conf_num(self.CONF_DODGE_COMBO_WAIT, 0.3)
        self.log_info(f"闪避后首平A测试: 闪避 → 等 {wait:.2f}s → 一个平A")
        SoundCombatContext.set_dodge_paused(True)
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self._prepare_input()
            io = _MacroIO(self)
            self.send_key(self.DODGE_KEY, down_time=0.02)  # 闪避(按一下shift)
            if wait > 0:
                time.sleep(wait)
            io.mouse_down()
            time.sleep(0.015)
            io.mouse_up()
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)
            SoundCombatContext.set_dodge_paused(False)
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
