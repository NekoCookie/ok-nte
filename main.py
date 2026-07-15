if __name__ == "__main__":
    import ok

    from src.cleanup import purge_old_debug_images  # [lw]
    from src.config import config

    purge_old_debug_images()  # [lw] 清理过期调试截图
    ok_instance = ok.OK(config)
    ok_instance.start()
