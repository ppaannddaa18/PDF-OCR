"""
字段匹配引擎 — PaddleOCR-VL 核心
将VLM返回的elements匹配到用户定义的regions

三级策略：
  Level 1: IoU精确匹配（element bbox与region bbox）
  Level 2: 就近搜索（在region周围搜索最近elements，合并相邻）
  Level 3: 关键词正则兜底（在markdown中搜索match_keywords）
"""
from typing import List, Dict, Optional, Tuple, Any
from collections import namedtuple

MatchResult = namedtuple('MatchResult', ['text', 'confidence', 'level', 'element'])


class FieldMatcher:
    """将OCR elements匹配到用户regions"""

    def __init__(self, config: dict):
        # 支持 gguf 和 rapidocr 配置
        gguf_cfg = config.get("ocr", {}).get("gguf", {})
        self.iou_threshold = gguf_cfg.get("match_iou_threshold", 0.5)
        self.neighbor_radius = gguf_cfg.get("match_neighbor_radius", 50)

    def match(self, elements: List[dict], regions: List[Any],
              markdown_text: str = "", pixel_bboxes: Dict[str, List[float]] = None) -> Dict[str, MatchResult]:
        """
        主匹配方法。

        Args:
            elements: PaddleOCR-VL返回的elements列表
            regions: 用户定义的Region列表
            markdown_text: 整页markdown文本（用于Level 3兜底）
            pixel_bboxes: {region.id: [x1,y1,x2,y2]} 像素坐标字典（不修改region对象）

        Returns:
            {region.id: MatchResult(text, confidence, level, element)}
        """
        results: Dict[str, MatchResult] = {}
        remaining = list(elements)  # 可消耗的element池
        bboxes = pixel_bboxes or {}

        for region in regions:
            region_bbox = bboxes.get(region.id)
            # Level 1: IoU匹配
            best = self._iou_match(region, remaining, region_bbox)
            if best is not None:
                remaining.remove(best)
                results[region.id] = MatchResult(
                    text=best.get("text", ""),
                    confidence=best.get("confidence", 0.0),
                    level=1,
                    element=best,
                )
                continue

            # Level 2: 就近搜索
            best = self._neighbor_match(region, remaining, region_bbox)
            if best is not None:
                remaining.remove(best)
                text, consumed = self._merge_adjacent(best, remaining)
                for elem in consumed:
                    remaining.remove(elem)
                results[region.id] = MatchResult(
                    text=text,
                    confidence=best.get("confidence", 0.0),
                    level=2,
                    element=best,
                )
                continue

            # Level 3: 关键词兜底
            text, conf = self._keyword_match(region, markdown_text)
            if text:
                results[region.id] = MatchResult(
                    text=text, confidence=conf, level=3, element=None,
                )
                continue

            # 未匹配
            results[region.id] = MatchResult(
                text="", confidence=0.0, level=0, element=None,
            )

        return results

    def _calculate_iou(self, box_a: List[float], box_b: List[float]) -> float:
        """计算两个bbox的IoU (Intersection over Union)"""
        xa1, ya1, xa2, ya2 = box_a
        xb1, yb1, xb2, yb2 = box_b

        xi1 = max(xa1, xb1)
        yi1 = max(ya1, yb1)
        xi2 = min(xa2, xb2)
        yi2 = min(ya2, yb2)

        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0

        inter = (xi2 - xi1) * (yi2 - yi1)
        area_a = (xa2 - xa1) * (ya2 - ya1)
        area_b = (xb2 - xb1) * (yb2 - yb1)
        union = area_a + area_b - inter

        return inter / union if union > 0 else 0.0

    def _iou_match(self, region, elements: List[dict], region_bbox: List[float]) -> Optional[dict]:
        """Level 1: 找到与region IoU最高的element"""
        if region_bbox is None:
            return None
        best_iou = 0.0
        best_elem = None
        for elem in elements:
            elem_bbox = elem.get("bbox")
            if not elem_bbox or len(elem_bbox) != 4:
                continue
            iou = self._calculate_iou(region_bbox, elem_bbox)
            if iou > best_iou:
                best_iou = iou
                best_elem = elem
        if best_iou >= self.iou_threshold and best_elem is not None:
            return best_elem
        return None

    def _neighbor_match(self, region, elements: List[dict], region_bbox: List[float]) -> Optional[dict]:
        """Level 2: 在region周围搜索最近的element"""
        if not elements or region_bbox is None:
            return None
        rx1, ry1, rx2, ry2 = region_bbox
        rcx, rcy = (rx1 + rx2) / 2, (ry1 + ry2) / 2

        best_dist = float('inf')
        best_elem = None
        for elem in elements:
            bbox = elem.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            ecx = (bbox[0] + bbox[2]) / 2
            ecy = (bbox[1] + bbox[3]) / 2
            dist = ((rcx - ecx) ** 2 + (rcy - ecy) ** 2) ** 0.5
            if dist < best_dist and dist <= self.neighbor_radius:
                best_dist = dist
                best_elem = elem
        return best_elem

    def _merge_adjacent(self, best: dict, remaining: List[dict], page_height: int = None) -> Tuple[str, List[dict]]:
        """合并与best相邻的同一行elements，返回(merged_text, consumed_elements)

        - Y 轴容差 DPI 感知：以行盒高度中位数（下限 20px）为基准，
          与 finance_processor._find_neighbor 的 B7 修复口径一致；
          page_height 参数保留兼容（不再参与容差计算）。
        - 合并顺序按 X 坐标升序（best 与其左右邻居统一排序），
          修复原实现"左侧元素文本排在 best 之后"的乱序问题。
        """
        best_bbox = best.get("bbox") or [0, 0, 0, 0]
        by_mid = (best_bbox[1] + best_bbox[3]) / 2
        consumed = []

        # 收集同一行（Y 中点接近）且水平相邻的元素
        candidates = []
        for elem in list(remaining):
            bbox = elem.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            ey_mid = (bbox[1] + bbox[3]) / 2
            candidates.append((elem, bbox, ey_mid))

        if candidates:
            heights = sorted(abs(b[3] - b[1]) for _, b, _ in candidates if b[3] > b[1])
            median_h = heights[len(heights) // 2] if heights else 30
            y_tolerance = max(20, int(median_h * 1.5))
        else:
            y_tolerance = 30

        for elem, bbox, ey_mid in candidates:
            if abs(ey_mid - by_mid) >= y_tolerance:
                continue
            # 水平相邻：与 best 左右间距均小于 neighbor_radius * 2
            if bbox[2] <= best_bbox[0] and best_bbox[0] - bbox[2] < self.neighbor_radius * 2:
                consumed.append(elem)
            elif bbox[0] >= best_bbox[2] and bbox[0] - best_bbox[2] < self.neighbor_radius * 2:
                consumed.append(elem)

        ordered = [best] + consumed
        ordered.sort(key=lambda e: (e.get("bbox") or [0, 0, 0, 0])[0])
        texts = [e.get("text", "") for e in ordered]
        return " ".join(texts), consumed

    def _keyword_match(self, region, markdown_text: str) -> Tuple[str, float]:
        """Level 3: 在markdown中用关键词正则搜索"""
        import re
        if not markdown_text or not region.match_keywords:
            return "", 0.0

        for kw in region.match_keywords:
            if not kw or not kw.strip():
                continue
            # 匹配 "关键词：值"、"**关键词**: 值" 等格式
            # 支持markdown粗体标记（**关键词**）以及多种分隔符
            pattern = r'\*{0,2}' + re.escape(kw) + r'\*{0,2}[：:\s]*([^\n]+)'
            m = re.search(pattern, markdown_text)
            if m:
                matched_text = m.group(1).strip()
                # 截断到下一个关键字（blob 文本中值常与后续标签粘连，
                # 如 "预录入编号：123 海关编号：456" 只取 "123"）
                for other in region.match_keywords:
                    if not other or other == kw:
                        continue
                    idx = matched_text.find(other)
                    if idx != -1:
                        matched_text = matched_text[:idx]
                        break
                matched_text = matched_text.strip().strip("。．，,、；;：:")
                if not matched_text:
                    continue
                # 置信度基于匹配文本长度与关键词长度的比例
                kw_len = len(kw)
                text_len = len(matched_text)
                confidence = min(0.5 + text_len / max(100, kw_len * 2), 0.95) if text_len > 0 else 0.5
                return matched_text, confidence

        return "", 0.0
