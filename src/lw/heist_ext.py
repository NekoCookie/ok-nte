"""LW configuration adapters for Pink Paw Heist routes."""

PATH1_INITIAL_W_DEFAULT = 2.68
PATH1_INITIAL_D_DEFAULT = 2.55
CONF_PATH1_INITIAL_W = "粉爪路径1开局W时长(s)"
CONF_PATH1_INITIAL_D = "粉爪路径1开局D时长(s)"


def path1_initial_move_durations(config):
    """Return the configurable Path 1 opening W and D durations in seconds."""
    return (
        _read_duration(
            config,
            CONF_PATH1_INITIAL_W,
            PATH1_INITIAL_W_DEFAULT,
        ),
        _read_duration(
            config,
            CONF_PATH1_INITIAL_D,
            PATH1_INITIAL_D_DEFAULT,
        ),
    )


def _read_duration(config, key, default):
    get = getattr(config, "get", None)
    if not callable(get):
        return default
    try:
        value = float(get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default
