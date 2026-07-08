"""LayoutExtractor — PaddleOCR-VL Result → 统一 Block[] 结构"""
from typing import List
import logging
from app.models.page_result import Block

logger = logging.getLogger("PDFOCR")


def extract_blocks(output) -> List[Block]:
    """
    从 PaddleOCR-VL Result 提取 blocks。

    Result 结构:
      .json -> overall_ocr_res (dt_polys, rec_texts, rec_scores)
             + parsing_res_list (block_bbox, block_label, block_content)
      .markdown -> markdown_texts
    """
    blocks = []
    try:
        data = output.json if hasattr(output, 'json') else (output if isinstance(output, dict) else {})
        # 从 overall_ocr_res 提取文字块
        ocr_res = data.get("overall_ocr_res", {})
        rec_texts = ocr_res.get("rec_texts", [])
        rec_scores = ocr_res.get("rec_scores", [])
        dt_polys = ocr_res.get("dt_polys", [])

        for i, text in enumerate(rec_texts):
            if not text or not text.strip():
                continue
            bbox = None
            if i < len(dt_polys):
                poly = dt_polys[i]
                if len(poly) >= 4:
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
            try:
                confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
            except (TypeError, ValueError):
                confidence = 0.0
            blocks.append(Block(
                block_type="text",
                content=text,
                bbox=bbox or [0, 0, 0, 0],
                confidence=confidence,
            ))

        # 从 parsing_res_list 提取结构化块（表格/公式/图表/印章）
        label_map = {
            "table": "table",
            "formula": "formula",
            "chart": "chart",
            "seal": "seal",
        }
        for item in data.get("parsing_res_list", []):
            block_label = item.get("block_label", "")
            mapped = label_map.get(block_label, "text")
            content = item.get("block_content", "")
            coord = item.get("block_bbox", None)

            bbox = None
            if coord and isinstance(coord, list) and len(coord) >= 4:
                if isinstance(coord[0], (list, tuple)):
                    xs = [p[0] for p in coord]
                    ys = [p[1] for p in coord]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                elif all(isinstance(v, (int, float)) for v in coord):
                    if len(coord) > 4:
                        # 多边形坐标 [x1,y1,x2,y2,...] → bbox [min_x, min_y, max_x, max_y]
                        xs = coord[0::2]
                        ys = coord[1::2]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]
                    else:
                        bbox = list(coord)
            blocks.append(Block(
                block_type=mapped,
                content=content if isinstance(content, str) else str(content),
                bbox=bbox or [0, 0, 0, 0],
                confidence=0.95,
            ))

    except Exception as e:
        logger.warning(f"LayoutExtractor: block extraction failed: {e}")
    return blocks


def extract_markdown(output) -> str:
    """从 Result 提取全页 Markdown"""
    try:
        md = output.markdown if hasattr(output, 'markdown') else {}
        if isinstance(md, dict):
            texts = md.get("markdown_texts", [])
            return "\n\n".join(texts) if texts else ""
        return str(md) if md else ""
    except Exception:
        return ""


def extract_raw_json(output) -> dict:
    """从 Result 提取原始 JSON"""
    try:
        return output.json if hasattr(output, 'json') else (output if isinstance(output, dict) else {})
    except Exception:
        return {}
