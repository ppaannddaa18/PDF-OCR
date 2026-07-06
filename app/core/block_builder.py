"""BlockBuilder — RapidOCR 手动框选结果 → 统一 Block[] 结构"""
from typing import List, Dict, Tuple
from app.models.page_result import Block
from app.models.region import Region


def build_blocks(
    regions: List[Region],
    ocr_results: Dict[str, Tuple[str, float]],
    image_size: Tuple[int, int],
) -> List[Block]:
    """
    将 RapidOCR 手动框选结果转换为 Block[]。

    Args:
        regions: 用户定义的框选区域列表
        ocr_results: {region_id: (text, confidence)}
        image_size: (width, height) 用于坐标归一化→像素转换

    Returns:
        Block 列表，每个 block 对应一个 region
    """
    W, H = image_size
    blocks = []
    for region in regions:
        result = ocr_results.get(region.id, ("", 0.0))
        text, confidence = result if isinstance(result, tuple) else (str(result), 0.0)
        # 归一化坐标 → 像素坐标
        bbox = [
            region.x * W,
            region.y * H,
            (region.x + region.w) * W,
            (region.y + region.h) * H,
        ]
        blocks.append(Block(
            block_type="text",
            content=text,
            bbox=bbox,
            confidence=float(confidence),
            meta={
                "region_id": region.id,
                "field_name": region.field_name,
                "ocr_mode": region.ocr_mode,
            },
        ))
    return blocks
