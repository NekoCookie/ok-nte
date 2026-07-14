import ok

from src.cleanup import purge_old_debug_images  # [lw]
from src.config import config

if __name__ == "__main__":
    purge_old_debug_images()  # [lw] 清理过期调试截图
    config = config
    ok = ok.OK(config)
    ok.start()
