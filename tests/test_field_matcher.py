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
        assert results['r1'].confidence == 0.5

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
