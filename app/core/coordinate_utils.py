def pixel_to_ratio(px: int, py: int, pw: int, ph: int, img_w: int, img_h: int) -> tuple:
    """像素坐标 → 归一化比例"""
    return px / img_w, py / img_h, pw / img_w, ph / img_h


def ratio_to_pixel(rx: float, ry: float, rw: float, rh: float, img_w: int, img_h: int) -> tuple:
    """归一化比例 → 像素坐标"""
    return int(rx * img_w), int(ry * img_h), int(rw * img_w), int(rh * img_h)
