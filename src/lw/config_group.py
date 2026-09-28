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
