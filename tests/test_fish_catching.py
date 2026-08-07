import unittest

import cv2
import numpy as np

from src.lw.fish_catch_ext import FishCatchingTaskMixin


class TestFishCatchingVision(unittest.TestCase):
    def test_detects_separate_neon_fish_shapes(self):
        image = np.zeros((240, 400, 3), dtype=np.uint8)
        image[:] = (170, 130, 80)
        cv2.ellipse(image, (110, 90), (42, 14), 15, 0, 360, (255, 255, 255), 4)
        cv2.ellipse(image, (290, 160), (28, 10), -20, 0, 360, (90, 255, 170), 4)

        targets = FishCatchingTaskMixin.detect_fish_components(image)

        self.assertGreaterEqual(len(targets), 2)
        centers = {(x + width // 2, y + height // 2) for x, y, width, height in targets}
        self.assertTrue(any(abs(x - 110) < 20 and abs(y - 90) < 20 for x, y in centers))
        self.assertTrue(any(abs(x - 290) < 20 and abs(y - 160) < 20 for x, y in centers))


if __name__ == "__main__":
    unittest.main()
