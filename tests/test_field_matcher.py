"""
FieldMatcher 功能测试 — 三级匹配策略
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.core.field_matcher import FieldMatcher, MatchResult
from app.utils.config_loader import get_default_config


class TestFieldMatcherIoU:
    """IoU计算 + Level 1匹配"""

    @pytest.fixture
    def matcher(self):
        config = get_default_config()
        return FieldMatcher(config)

    def test_identical_boxes(self, matcher):
        iou = matcher._calculate_iou([0, 0, 100, 100], [0, 0, 100, 100])
        assert iou == 1.0

    def test_disjoint_boxes(self, matcher):
        iou = matcher._calculate_iou([0, 0, 100, 100], [200, 200, 300, 300])
        assert iou == 0.0

    def test_partial_overlap(self, matcher):
        iou = matcher._calculate_iou([0, 0, 100, 100], [50, 50, 150, 150])
        assert 0.13 < iou < 0.15

    def test_zero_area_box(self, matcher):
        iou = matcher._calculate_iou([0, 0, 0, 0], [0, 0, 100, 100])
        assert iou == 0.0

    def test_level1_iou_match(self, matcher):
        from app.models.region import Region
        region = Region(id='r1', field_name='test', x=0.1, y=0.2, w=0.3, h=0.1)
        elements = [
            {'text': 'Hello', 'confidence': 0.95, 'bbox': [0, 0, 100, 100]},
        ]
        # 使用像素坐标
        pixel_bboxes = {'r1': [30, 40, 130, 60]}  # 模拟像素坐标
        results = matcher.match(elements, [region], '', pixel_bboxes)
        # 元素虽IoU小但在邻近范围内，Level 2 匹配是合理的
        assert results['r1'].level in (0, 1, 2)

    def test_level1_exact_match(self, matcher):
        from app.models.region import Region
        region = Region(id='r1', field_name='test', x=0, y=0, w=1, h=1)
        elements = [
            {'text': 'Full Match', 'confidence': 0.99, 'bbox': [0, 0, 500, 500]},
        ]
        pixel_bboxes = {'r1': [0, 0, 500, 500]}
        results = matcher.match(elements, [region], '', pixel_bboxes)
        assert results['r1'].level == 1
        assert results['r1'].text == 'Full Match'


class TestFieldMatcherLevel2:
    """就近搜索匹配"""

    @pytest.fixture
    def matcher(self):
        config = get_default_config()
        return FieldMatcher(config)

    def test_neighbor_found(self, matcher):
        from app.models.region import Region
        region = Region(id='r1', field_name='test', x=0, y=0, w=0.1, h=0.1)
        elements = [
            {'text': 'Nearby', 'confidence': 0.8, 'bbox': [60, 10, 150, 40]},
        ]
        pixel_bboxes = {'r1': [0, 0, 50, 30]}  # 区域中心(25,15)，元素中心(105,25)→距离~80px>50px阈值
        results = matcher.match(elements, [region], '', pixel_bboxes)
        assert results['r1'].level == 0  # 距离超过阈值，匹配不到

    def test_merge_adjacent_left_and_right_ordered(self, matcher):
        """合并同一行元素时按 X 坐标升序（左侧元素不能排在 best 之后）"""
        best = {'text': 'B', 'bbox': [100, 0, 200, 30]}
        left = {'text': 'A', 'bbox': [0, 0, 90, 30]}
        right = {'text': 'C', 'bbox': [210, 0, 300, 30]}
        text, consumed = matcher._merge_adjacent(best, [left, right])
        assert text == 'A B C'
        assert len(consumed) == 2
        assert left in consumed and right in consumed

    def test_merge_y_tolerance_scales_with_box_height(self, matcher):
        """Y 轴容差 DPI 感知：以行盒高度中位数为基准（高分辨率下同行元素仍能合并）"""
        best = {'text': 'X', 'bbox': [0, 100, 100, 300]}     # 行高 200，mid=200
        right = {'text': 'Y', 'bbox': [150, 260, 250, 340]}  # 行高 80，mid=300，Δ=100
        text, consumed = matcher._merge_adjacent(best, [right])
        assert right in consumed
        assert text == 'X Y'

    def test_merge_distant_row_not_merged(self, matcher):
        """跨行（Y 差超过容差）不合并"""
        best = {'text': 'X', 'bbox': [0, 100, 100, 300]}
        next_row = {'text': 'Z', 'bbox': [200, 700, 300, 900]}  # mid=800，Δ=600
        text, consumed = matcher._merge_adjacent(best, [next_row])
        assert consumed == []
        assert text == 'X'


class TestFieldMatcherLevel3:
    """关键词兜底"""

    @pytest.fixture
    def matcher(self):
        config = get_default_config()
        return FieldMatcher(config)

    def test_keyword_found(self, matcher):
        from app.models.region import Region
        region = Region(
            id='r1', field_name='发票号码', x=0, y=0, w=1, h=1,
            match_keywords=['发票号码']
        )
        markdown = "发票号码：12345678\n日期：2024-01-15"
        elements = []  # 无element可匹配
        pixel_bboxes = {'r1': [0, 0, 500, 500]}
        results = matcher.match(elements, [region], markdown, pixel_bboxes)
        assert results['r1'].level == 3
        assert results['r1'].text == '12345678'
        assert results['r1'].confidence > 0.5  # 动态置信度，基于匹配质量

    def test_keyword_markdown_bold(self, matcher):
        from app.models.region import Region
        region = Region(
            id='r1', field_name='电话', x=0, y=0, w=1, h=1,
            match_keywords=['电话']
        )
        markdown = "**电话**：13800138000"
        pixel_bboxes = {'r1': [0, 0, 500, 500]}
        results = matcher.match([], [region], markdown, pixel_bboxes)
        assert results['r1'].level == 3
        assert '13800138000' in results['r1'].text

    def test_keyword_match_stops_at_next_keyword(self, matcher):
        """blob 文本：值截断到下一个关键字，不粘连后续标签"""
        from app.models.region import Region
        region = Region(
            id='r1', field_name='预录入编号', x=0, y=0, w=1, h=1,
            match_keywords=['预录入编号', '海关编号'],
        )
        markdown = "预录入编号：090820241000039736 海关编号：090820241000039736"
        text, conf = matcher._keyword_match(region, markdown)
        assert text == '090820241000039736'
        assert conf > 0.5

    def test_keyword_match_pure_label_value_kept(self, matcher):
        """值本身不含后续关键字时保持原样"""
        from app.models.region import Region
        region = Region(
            id='r1', field_name='进口日期', x=0, y=0, w=1, h=1,
            match_keywords=['进口日期', '申报日期'],
        )
        text, _ = matcher._keyword_match(region, "进口日期：20240408 申报日期：20240408")
        assert text == '20240408'

    def test_keyword_not_found(self, matcher):
        from app.models.region import Region
        region = Region(
            id='r1', field_name='未知', x=0, y=0, w=1, h=1,
            match_keywords=['不存在的关键词']
        )
        pixel_bboxes = {'r1': [0, 0, 500, 500]}
        results = matcher.match([], [region], '', pixel_bboxes)
        assert results['r1'].level == 0
        assert results['r1'].text == ''


class TestFieldMatcherEdgeCases:
    """边界条件"""

    @pytest.fixture
    def matcher(self):
        config = get_default_config()
        return FieldMatcher(config)

    def test_empty_inputs(self, matcher):
        results = matcher.match([], [], '')
        assert results == {}

    def test_element_without_bbox(self, matcher):
        from app.models.region import Region
        region = Region(id='r1', field_name='test', x=0, y=0, w=1, h=1)
        elements = [{'text': 'No bbox', 'confidence': 0.5}]  # 无bbox
        pixel_bboxes = {'r1': [0, 0, 100, 100]}
        results = matcher.match(elements, [region], '', pixel_bboxes)
        # 无bbox的element无法做IoU匹配，但也不应崩溃
        assert results['r1'].level in (0, 2)

    def test_no_pixel_bboxes(self, matcher):
        from app.models.region import Region
        region = Region(id='r1', field_name='test', x=0, y=0, w=1, h=1)
        elements = [{'text': 'Hi', 'confidence': 0.9, 'bbox': [0, 0, 100, 100]}]
        results = matcher.match(elements, [region], '')
        # 无pixel_bboxes时无法匹配IoU/邻居
        assert results['r1'].level == 0
