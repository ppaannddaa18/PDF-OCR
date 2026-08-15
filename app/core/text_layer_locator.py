"""PDF 文本层定位 — fitz 词级坐标匹配（核对高亮的唯一坐标源）

PDF 文本层坐标为 pt（72dpi 基准）；画布场景坐标是渲染 DPI 的图像像素。
调用方传 scale = render_dpi / 72 换算，与 PdfCanvas 场景一致。
页面 rotation ≠ 0 时（如 90° 扫描件），get_text("words") 返回文档坐标，
须先经 page.rotation_matrix 变换为旋转后渲染坐标再缩放，否则高亮框
画在画布外（GUI 实测：y=1864-2226 超出画布高 1653）。
无文本层 / 未找到 → 返回 []（调用方只渲染不高亮）。
"""
from typing import List, Optional

import fitz


def locate_words(page, text: str, scale: float = 1.0,
                 first_only: bool = True) -> List[List[float]]:
    """在 PDF 页文本层定位 text（跨词匹配，忽略空白差异）。

    Args:
        page: fitz.Page 对象
        text: 要定位的文本（关键字或提取值）
        scale: pt → 像素换算系数（render_dpi / 72）
        first_only: True 只返回首现矩形；False 返回全部

    Returns:
        矩形列表 [x0, y0, x1, y1]（像素坐标）；未找到 → []
    """
    if not text:
        return []
    try:
        words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,no)
    except Exception:
        return []
    if not words:
        return []
    needle = text.replace(" ", "")
    # 文档坐标 → 旋转后渲染坐标（rotation=0 时 rotation_matrix 为单位矩阵）
    rects = []
    for w in words:
        r = fitz.Rect(w[0], w[1], w[2], w[3]) * page.rotation_matrix
        rects.append((r.x0, r.y0, r.x1, r.y1))
    seq = [w[4].replace(" ", "") for w in words]
    n = len(words)
    found: List[List[float]] = []
    for i in range(n):
        if found and first_only:
            break
        joined = ""
        for j in range(i, min(n, i + 64)):
            joined += seq[j]
            if needle in joined:
                # needle 在拼接串中的字符范围 [pos, end)，映射回覆盖它的 word
                # 下标 [k0, k1]（只取覆盖段，不从行首合并无关词）
                pos = joined.find(needle)
                end = pos + len(needle)
                acc = 0
                k0 = k1 = None
                for k in range(i, j + 1):
                    wlen = len(seq[k])
                    if k0 is None and acc + wlen > pos:
                        k0 = k
                    if acc + wlen >= end:
                        k1 = k
                        break
                    acc += wlen
                xs = [rects[k][0] for k in range(k0, k1 + 1)]
                ys = [rects[k][1] for k in range(k0, k1 + 1)]
                xe = [rects[k][2] for k in range(k0, k1 + 1)]
                ye = [rects[k][3] for k in range(k0, k1 + 1)]
                found.append([min(xs) * scale, min(ys) * scale,
                              max(xe) * scale, max(ye) * scale])
                break
    return found
