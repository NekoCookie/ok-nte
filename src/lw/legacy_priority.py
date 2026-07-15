# [lw] 上游 planner 化(38b49f8 等)后从 BaseChar 移除了 Priority/Role(旧版)与
# get_switch_priority 优先级机制;龙威的切换决策(lw_decide_switch_to)与用户角色
# (MainDps.py 等)仍基于该机制,故整体迁移到本文件与 CharExtMixin 维护。
# 来源: merge-base 46e9225 的 src/char/BaseChar.py 原版定义。
from enum import IntEnum, StrEnum


class Priority(IntEnum):
    """定义切换角色的优先级枚举。"""

    MIN = -999999999  # 最低优先级
    SWITCH_CD = -1000  # 切换冷却中
    CURRENT_CHAR = -100  # 当前角色
    CURRENT_CHAR_PLUS = CURRENT_CHAR + 1  # 当前角色稍高优先级 (特殊情况)
    SKILL_AVAILABLE = 100  # 有可用技能
    BASE_MINUS_1 = -1
    BASE = 0
    MAX = 9999999999  # 最高优先级
    FAST_SWITCH = MAX - 100  # 快速切换优先级 (例如应对特殊机制)


class Role(StrEnum):
    """定义角色定位枚举(旧版, 含 DEFAULT/HEALER; 与 planner 的 Role 不同)。"""

    DEFAULT = "Default"  # 默认/未知定位
    SUB_DPS = "Sub DPS"  # 副输出
    MAIN_DPS = "Main DPS"  # 主输出
    HEALER = "Healer"  # 治疗者
