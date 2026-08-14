"""Source entry point for the ok-nte GUI."""

import ctypes
import json
from pathlib import Path


def _repair_saved_window_geometry(config: dict) -> None:
    """Keep a saved GUI position visible after monitor/layout changes.

    Qt restores the last position before the user can interact with the window. A
    position from a disconnected monitor therefore makes a successful launch look
    like a failed one. This preflight only changes the position when the saved
    rectangle is completely outside the current virtual desktop.
    """
    if not isinstance(config, dict) or "config_folder" not in config:
        return

    config_path = Path(config["config_folder"]) / "_ok.json"
    try:
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            return

        x = int(saved.get("window_x", 0))
        y = int(saved.get("window_y", 0))
        width = max(1, int(saved.get("window_width", 1200)))
        height = max(1, int(saved.get("window_height", 800)))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return

    if not hasattr(ctypes, "windll"):
        return

    try:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))
        top = int(user32.GetSystemMetrics(77))
        desktop_width = int(user32.GetSystemMetrics(78))
        desktop_height = int(user32.GetSystemMetrics(79))
    except (AttributeError, OSError):
        return

    right = left + desktop_width
    bottom = top + desktop_height
    margin = 80
    fully_offscreen = (
        x + width <= left + margin
        or x >= right - margin
        or y + height <= top + margin
        or y >= bottom - margin
    )
    if not fully_offscreen:
        return

    saved["window_x"] = max(left, left + (desktop_width - width) // 2)
    saved["window_y"] = max(top, top + (desktop_height - height) // 2)
    try:
        config_path.write_text(
            json.dumps(saved, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


if __name__ == "__main__":
    from src.config import config
    from src.patches.startup_patches import install_startup_patches

    install_startup_patches()

    import ok

    from src.cleanup import purge_old_debug_images  # [lw]

    _repair_saved_window_geometry(config)
    purge_old_debug_images()  # [lw] 清理过期调试截图
    ok_instance = ok.OK(config)
    ok_instance.start()
