from src.char.Requiem import Requiem
from src.lw.combat_templates import BuffSupport, HealSupport, MainDps, SakiriBuffSupport


def register_lw_char_implementations(registry):
    """Register user templates that are outside the upstream character package."""
    registry.register(
        "builtin:template_main_dps",
        MainDps,
        cn_name="主C模板",
    )
    registry.register(
        "builtin:template_buff_support",
        BuffSupport,
        cn_name="辅助模板",
    )
    registry.register(
        "builtin:template_heal_support",
        HealSupport,
        cn_name="治疗模板",
    )
    registry.register(
        "builtin:template_sakiri_buff_support",
        SakiriBuffSupport,
        cn_name="早雾辅助",
    )
    registry.register(
        "builtin:requiem",
        Requiem,
        cn_name="安魂曲主C",
    )
