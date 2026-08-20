"""LW configuration adapters for Pink Paw Heist routes."""

from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


PATH1_INITIAL_W_DEFAULT = 2.68
PATH1_INITIAL_D_DEFAULT = 2.55


def path1_initial_move_durations(task):
    """Return the configurable Path 1 opening W and D durations in seconds."""
    config_task = task.get_task_by_class(RequiemCombatConfigTask)
    config = getattr(config_task, "config", None)
    return (
        _read_duration(
            config,
            RequiemCombatConfigTask.CONF_HEIST_PATH1_INITIAL_W,
            PATH1_INITIAL_W_DEFAULT,
        ),
        _read_duration(
            config,
            RequiemCombatConfigTask.CONF_HEIST_PATH1_INITIAL_D,
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
