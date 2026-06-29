"""启动时的本地产物清理。

目前只清 logs/box_debug —— 那是程序唯一自动生成、受 SKILL_CD_DIAG 开关控制的技能图标
调试截图,容易堆积。logs 下其它中文目录(技能就绪模板/治疗看图/模板验证看图等)是手工
素材,代码无写入引用,这里一律不碰。
"""
import os
import time

# 默认保留时长:超过这个小时数的调试截图在启动时清掉。
DEBUG_IMAGE_MAX_AGE_HOURS = 48
DEBUG_IMAGE_DIR = os.path.join("logs", "box_debug")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def purge_old_images(directory, max_age_hours=DEBUG_IMAGE_MAX_AGE_HOURS, exts=_IMAGE_EXTS):
    """删除 directory 下修改时间超过 max_age_hours 的图片(只删文件本身, 不删目录)。

    任何异常都吞掉, 绝不影响软件启动。返回 (删除数, 释放字节)。
    """
    removed, freed = 0, 0
    try:
        if not os.path.isdir(directory):
            return removed, freed
        cutoff = time.time() - max_age_hours * 3600
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if not os.path.isfile(path) or not name.lower().endswith(exts):
                    continue
                if os.path.getmtime(path) >= cutoff:
                    continue
                size = os.path.getsize(path)
                os.remove(path)
                removed += 1
                freed += size
            except OSError:
                continue  # 单个文件被占用/无权限就跳过, 不影响其它
    except Exception:
        pass
    return removed, freed


def purge_old_debug_images(max_age_hours=DEBUG_IMAGE_MAX_AGE_HOURS):
    """启动清理入口:只清 logs/box_debug 里的过期调试截图。"""
    removed, freed = purge_old_images(DEBUG_IMAGE_DIR, max_age_hours)
    if removed:
        print(f"[启动清理] {DEBUG_IMAGE_DIR}: 删除 {removed} 张 {max_age_hours}h+ 调试截图, "
              f"释放 {freed / 1024:.0f} KB")
    return removed, freed
