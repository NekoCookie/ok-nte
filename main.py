import ok

from src.cleanup import purge_old_debug_images
from src.config import config

if __name__ == "__main__":
    purge_old_debug_images()
    config = config
    ok = ok.OK(config)
    ok.start()
