"""[lw] Declarative folded config groups for ok-script config cards.

A group is stored as a boolean config whose True branch lists its children. The
Qt config card renders it as an expandable header (see ``config_group_ui``);
other UIs fall back to the framework's boolean switch.
"""

CONFIG_GROUP_MARKER = "lw_config_group"


def config_group(config_keys):
    """Build the ``config_type`` entry of a folded group containing ``config_keys``."""
    return {CONFIG_GROUP_MARKER: True, "sub_configs": {True: list(config_keys)}}


def is_config_group(the_type):
    return isinstance(the_type, dict) and the_type.get(CONFIG_GROUP_MARKER) is True


def config_group_keys(config_type):
    return {key for key, the_type in (config_type or {}).items() if is_config_group(the_type)}


def config_group_depth(config_type, key):
    """How many ``sub_configs`` parents ``key`` has, counted only when a folded group is among them.

    The config card indents every sub config by a single fixed step, so nested groups would
    render flat. The Qt header adds ``depth - 1`` extra steps to restore the hierarchy.
    """
    parents = {}
    for parent, the_type in (config_type or {}).items():
        if not isinstance(the_type, dict) or not isinstance(the_type.get("sub_configs"), dict):
            continue
        for children in the_type["sub_configs"].values():
            for child in [children] if isinstance(children, str) else children or []:
                parents.setdefault(child, parent)
    depth, in_group, seen = 0, False, {key}
    while key in parents:
        key = parents[key]
        if key in seen:
            break
        seen.add(key)
        depth += 1
        in_group = in_group or is_config_group(config_type.get(key))
    return depth if in_group else 0
