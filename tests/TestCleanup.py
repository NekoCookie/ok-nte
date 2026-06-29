"""启动清理 purge_old_images 的回归测试:只删过期图片, 不碰新文件/非图片/子目录。"""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cleanup import purge_old_images


class TestPurgeOldImages(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def _mk(self, name, age_hours, size=100):
        path = os.path.join(self.d, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        t = time.time() - age_hours * 3600
        os.utime(path, (t, t))
        return path

    def test_removes_only_expired_images(self):
        self._mk("old1.png", 50)
        self._mk("old2.jpg", 72, size=200)
        self._mk("new.png", 10)          # 未到48h
        self._mk("old.txt", 100)         # 旧但非图片
        os.makedirs(os.path.join(self.d, "subdir"))

        removed, freed = purge_old_images(self.d, max_age_hours=48)

        self.assertEqual(removed, 2, "只应删两张过期图片")
        self.assertEqual(freed, 300, "释放字节应为两张图之和")
        left = set(os.listdir(self.d))
        self.assertEqual(left, {"new.png", "old.txt", "subdir"},
                         "新图/非图片/子目录都应保留")

    def test_case_insensitive_extension(self):
        self._mk("OLD.PNG", 50)
        removed, _ = purge_old_images(self.d, max_age_hours=48)
        self.assertEqual(removed, 1, "扩展名匹配应忽略大小写")

    def test_boundary_just_under_threshold_kept(self):
        self._mk("fresh.png", 47)  # 差一点不到48h
        removed, _ = purge_old_images(self.d, max_age_hours=48)
        self.assertEqual(removed, 0, "未超过阈值不应删除")

    def test_missing_directory_is_safe(self):
        self.assertEqual(purge_old_images(os.path.join(self.d, "nope")), (0, 0))

    def test_empty_directory(self):
        self.assertEqual(purge_old_images(self.d, max_age_hours=48), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
