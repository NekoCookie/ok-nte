# [lw] 用户角色注册表: CharFactory.char_dict 在定义后 update 本表,
# 这样 CharFactory.py 里只需两行接线, 新增/改动角色都在本文件进行。
from typing import Any

from src.char.MainDps import BuffSupport, HealSupport, MainDps, SakiriBuffSupport
from src.char.Requiem import Requiem

lw_char_dict: dict[str, dict[str, Any]] = {
    "template_main_dps": {"cls": MainDps, "cn_name": "主C模板"},
    "template_buff_support": {"cls": BuffSupport, "cn_name": "辅助模板"},
    "template_heal_support": {"cls": HealSupport, "cn_name": "治疗模板"},
    "template_sakiri_buff_support": {"cls": SakiriBuffSupport, "cn_name": "早雾辅助"},
    "char_requiem": {"cls": Requiem, "cn_name": "安魂曲主C"},
}
