"""安魂曲 4A跳A combo 的唯一数据源与执行器。

时序移植自 YiHuan-Macro 参考实现(方案一/方案二), 单位毫秒。宏测试任务
(RequiemJumpAttackTestTask)和实战主C(Requiem)共用这里的时序与执行器, 改一处两边同步。

执行器 run_scheme_* 只依赖一个 io 适配器(鸭子类型), 由调用方提供不同的底层收发:
  - mouse_down()/mouse_up(): 左键按下/抬起
  - space_down()/space_up(): 空格按下/抬起
  - sleep_ms(ms): 精确等待(务必用 raw sleep, 别插帧截图, 否则打乱 combo 节奏)
  - should_continue() -> bool: 每一下之前查, False 则立即中止(松手/闪避/切人)
"""

# 方案一(安魂曲): 14 次逐点 (按住ms, 抬起ms), 然后左键+空格同时按住起跳、一起松、停一拍, 收尾补一下。
SCHEME_A_CLICKS = [
    (79, 62), (78, 78), (63, 62), (47, 47), (63, 62), (47, 62), (47, 78),
    (47, 47), (78, 32), (62, 172), (62, 79), (93, 78), (79, 78), (47, 62),
]
SCHEME_A_JUMP_HOLD_MS = 78
SCHEME_A_JUMP_GAP_MS = 78
SCHEME_A_END_CLICK = (40, 40)

# 方案二(闪双4a): 5点 → 冲刺跳 → 2点 → 冲刺跳 → 2点。
SCHEME_B_CLICKS_1 = [(79, 46), (79, 46), (63, 47), (62, 47), (47, 31)]
SCHEME_B_CLICKS_2 = [(63, 47), (93, 32)]
# 冲刺跳: 左键+空格按住 → 松左键 → 左键+松空格 → 松左键(双段)。
SCHEME_B_DASH_MS = (31, 47, 94, 47)


def scheme_a_round_seconds():
    """方案一一整轮的理论时长(秒)。用于把主C idle 的 2.5s 改成"刚好打一轮"。"""
    total_ms = (
        sum(d + u for d, u in SCHEME_A_CLICKS)
        + SCHEME_A_JUMP_HOLD_MS
        + SCHEME_A_JUMP_GAP_MS
        + sum(SCHEME_A_END_CLICK)
    )
    return total_ms / 1000.0


def _click(io, down_ms, up_ms):
    """一次离散左键点击, 起手前查 should_continue。返回 False=已中止。"""
    if not io.should_continue():
        return False
    io.mouse_down()
    io.sleep_ms(down_ms)
    io.mouse_up()
    io.sleep_ms(up_ms)
    return True


def run_scheme_a(io):
    """跑一轮方案一(安魂曲 4A跳A)。任意一步 should_continue 变 False 立即返回。"""
    for down_ms, up_ms in SCHEME_A_CLICKS:
        if not _click(io, down_ms, up_ms):
            return
    if not io.should_continue():
        return
    io.mouse_down()
    io.space_down()
    io.sleep_ms(SCHEME_A_JUMP_HOLD_MS)
    io.mouse_up()
    io.space_up()
    io.sleep_ms(SCHEME_A_JUMP_GAP_MS)
    _click(io, *SCHEME_A_END_CLICK)


def _dash_jump(io):
    """方案二的冲刺跳: 左键+空格按住 → 松左键 → 左键+松空格 → 松左键(双段)。"""
    if not io.should_continue():
        return False
    hold1, gap1, hold2, gap2 = SCHEME_B_DASH_MS
    io.mouse_down()
    io.space_down()
    io.sleep_ms(hold1)
    io.mouse_up()
    io.sleep_ms(gap1)
    io.mouse_down()
    io.space_up()
    io.sleep_ms(hold2)
    io.mouse_up()
    io.sleep_ms(gap2)
    return True


def run_scheme_b(io):
    """跑一轮方案二(闪双4a)。"""
    for down_ms, up_ms in SCHEME_B_CLICKS_1:
        if not _click(io, down_ms, up_ms):
            return
    if not _dash_jump(io):
        return
    for down_ms, up_ms in SCHEME_B_CLICKS_2:
        if not _click(io, down_ms, up_ms):
            return
    if not _dash_jump(io):
        return
    for down_ms, up_ms in SCHEME_B_CLICKS_2:
        if not _click(io, down_ms, up_ms):
            return


# 方案三(精简 4A+跳A): 从原始录制精简而来, 保留原时间轴、只删被吞的重复点击。
# 原理: 前3下普攻极快(用原录制快节拍), 第4下普攻动画非常长——跳A 就插在第4下这段长动画里。
# 前3下(96/87、64/95、68/99)后, 第4下起手(72)再等 1180ms(第4下长动画, 原录制里那段冗余快点)→
# 空格正好落在原录制的 1761ms 位置(空格前总延迟分毫不差) → 空格(跳) → 一下左键(=跳A, 空格+左键,
# 在第4A过程中) → 后摇。空格前后总延迟均与原始录制一致。
# (按住ms, 之后等ms): A1-A3 用攻击节拍(~300ms)保证各落一段, 太小会被吞(实测87-99ms只出2段);
# A4 用长等待补偿, 让空格仍落在原录制的 1761ms。间隔是主要可调量: 吞刀就调大, 太慢就调小。
SCHEME_C_GROUND = [(80, 220), (80, 220), (80, 220), (80, 781)]
SCHEME_C_JUMP_HOLD_MS = 100   # 空格按住(跳); 位置/时长不动
SCHEME_C_JUMP_GAP_MS = 2
SCHEME_C_JUMPA_CLICK = (74, 275)  # 跳A那下左键(空格+左键) + 末尾后摇(对齐原录制总时长~2.21s)


def scheme_c_round_seconds():
    total_ms = (
        sum(d + u for d, u in SCHEME_C_GROUND)
        + SCHEME_C_JUMP_HOLD_MS
        + SCHEME_C_JUMP_GAP_MS
        + sum(SCHEME_C_JUMPA_CLICK)
    )
    return total_ms / 1000.0


def run_scheme_c(io, ground=None, jump_hold_ms=None, jump_gap_ms=None, jumpa_click=None):
    """跑一轮方案三(精简 4A+跳A)。所有时序可由调用方传参覆盖(不传用模块默认), 便于做成配置项:
    ground=[(按住ms,之后等ms)...] 4下地面普攻; jump_hold_ms/jump_gap_ms 空格; jumpa_click=(按住,后摇)。"""
    ground = SCHEME_C_GROUND if ground is None else ground
    jump_hold_ms = SCHEME_C_JUMP_HOLD_MS if jump_hold_ms is None else jump_hold_ms
    jump_gap_ms = SCHEME_C_JUMP_GAP_MS if jump_gap_ms is None else jump_gap_ms
    jumpa_click = SCHEME_C_JUMPA_CLICK if jumpa_click is None else jumpa_click
    for down_ms, up_ms in ground:
        if not _click(io, down_ms, up_ms):
            return
    if not io.should_continue():
        return
    io.space_down()          # 空格 = 跳(位置不变: 地面攻击后、跳A左键前)
    io.sleep_ms(jump_hold_ms)
    io.space_up()
    io.sleep_ms(jump_gap_ms)
    _click(io, *jumpa_click)  # 空格+这下左键 = 跳A(与第4A同时出)
