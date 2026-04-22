import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.coordinate_utils import pixel_to_ratio, ratio_to_pixel


class TestCoordinateUtils(unittest.TestCase):
    """坐标换算工具测试"""

    def test_pixel_to_ratio(self):
        """测试像素坐标转归一化比例"""
        # 像素坐标: (100, 200, 50, 80), 图像尺寸: (500, 400)
        rx, ry, rw, rh = pixel_to_ratio(100, 200, 50, 80, 500, 400)
        self.assertAlmostEqual(rx, 0.2)   # 100/500
        self.assertAlmostEqual(ry, 0.5)   # 200/400
        self.assertAlmostEqual(rw, 0.1)   # 50/500
        self.assertAlmostEqual(rh, 0.2)   # 80/400

    def test_ratio_to_pixel(self):
        """测试归一化比例转像素坐标"""
        # 比例坐标: (0.2, 0.5, 0.1, 0.2), 图像尺寸: (500, 400)
        px, py, pw, ph = ratio_to_pixel(0.2, 0.5, 0.1, 0.2, 500, 400)
        self.assertEqual(px, 100)   # 0.2 * 500
        self.assertEqual(py, 200)   # 0.5 * 400
        self.assertEqual(pw, 50)    # 0.1 * 500
        self.assertEqual(ph, 80)    # 0.2 * 400

    def test_round_trip(self):
        """测试往返转换"""
        # 像素 -> 比例 -> 像素
        original = (100, 200, 50, 80)
        img_size = (500, 400)
        ratio = pixel_to_ratio(*original, *img_size)
        result = ratio_to_pixel(*ratio, *img_size)
        self.assertEqual(result, original)


if __name__ == "__main__":
    unittest.main()
