import fitz
from PIL import Image
import io


class PdfLoader:
    def __init__(self, dpi: int = 200):
        self.dpi = dpi

    def render_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """渲染指定页为 PIL Image"""
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_num]
            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            return img
        finally:
            doc.close()

    def get_page_size(self, pdf_path: str, page_num: int = 0) -> tuple:
        """返回 PDF 页面原始尺寸 (width_pt, height_pt)"""
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_num]
            rect = page.rect
            return rect.width, rect.height
        finally:
            doc.close()

    def crop_region(self, pdf_path: str, region, page_num: int = 0) -> Image.Image:
        """根据归一化坐标裁剪区域"""
        img = self.render_page(pdf_path, page_num)
        W, H = img.size
        left = max(0, int(region.x * W))
        top = max(0, int(region.y * H))
        right = min(W, int((region.x + region.w) * W))
        bottom = min(H, int((region.y + region.h) * H))
        if right <= left or bottom <= top:
            return Image.new("RGB", (1, 1), (255, 255, 255))
        return img.crop((left, top, right, bottom))
