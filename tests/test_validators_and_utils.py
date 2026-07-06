"""
校验器 + LRU缓存 + 命令历史 功能测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time
from app.utils.validators import validate, validate_with_error, normalize_by_type
from app.utils.lru_cache import LRUCache
from app.utils.config_loader import get_default_config, load_config


# ==============================
# Validators
# ==============================

class TestValidators:
    """字段类型校验器"""

    def test_validate_email_valid(self):
        assert validate('test@example.com', 'email')

    def test_validate_email_plus_addressing(self):
        assert validate('user+tag@domain.com', 'email')

    def test_validate_email_invalid_leading_dot(self):
        assert not validate('.user@domain.com', 'email')

    def test_validate_email_invalid_double_dot(self):
        assert not validate('user..name@domain.com', 'email')

    def test_validate_phone_valid(self):
        assert validate('13800138000', 'phone')

    def test_validate_phone_invalid_short(self):
        assert not validate('12345', 'phone')

    def test_validate_phone_invalid_letters(self):
        assert not validate('abc12345678', 'phone')

    def test_validate_number_valid(self):
        assert validate('8800.00', 'number')
        assert validate('-123.45', 'number')
        assert validate('42', 'number')

    def test_validate_number_scientific(self):
        # 科学计数法应该被接受
        assert validate('1.5e10', 'number')

    def test_validate_number_trailing_dot(self):
        # "123." 不应通过
        assert not validate('123.', 'number')

    def test_validate_date_valid(self):
        assert validate('2024-01-15', 'date')

    def test_validate_date_slash_format(self):
        assert validate('2024/01/15', 'date')

    def test_validate_date_invalid(self):
        assert not validate('not-a-date', 'date')

    def test_validate_text_always_true(self):
        assert validate('', 'text')
        assert validate('anything', 'text')

    def test_normalize_date(self):
        result = normalize_by_type('2024/01/15', 'date')
        assert result == '2024-01-15'

    def test_normalize_number_removes_comma(self):
        result = normalize_by_type('1,234.56', 'number')
        assert result == '1234.56'

    def test_normalize_number_negative(self):
        result = normalize_by_type('-123.45', 'number')
        assert result == '-123.45'

    def test_empty_value_falls_through(self):
        # 空值对所有field_type都应通过（非"required"逻辑）
        for ft in ['text', 'number', 'date', 'email', 'phone']:
            is_valid, _ = validate_with_error('', ft)
            assert is_valid, f"Empty should pass for {ft}"


# ==============================
# LRU Cache
# ==============================

class TestLRUCache:
    """LRU缓存测试"""

    def test_basic_set_get(self):
        cache = LRUCache(max_size=10)
        cache.set('a', 1)
        assert cache.get('a') == 1
        assert cache['a'] == 1

    def test_eviction(self):
        cache = LRUCache(max_size=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)  # 驱逐最旧的 'a'
        assert cache.get('a') is None
        assert cache['b'] == 2
        assert cache['c'] == 3

    def test_ttl_expiry(self):
        cache = LRUCache(max_size=10, ttl_seconds=0.1)
        cache.set('x', 'value')
        assert cache.get('x') == 'value'
        time.sleep(0.15)
        assert cache.get('x') is None  # 已过期

    def test_ttl_getitem_raises(self):
        cache = LRUCache(max_size=10, ttl_seconds=0.1)
        cache.set('x', 'value')
        time.sleep(0.15)
        with pytest.raises(KeyError):
            _ = cache['x']  # __getitem__ 也应检查TTL

    def test_contains_ttl(self):
        cache = LRUCache(max_size=10, ttl_seconds=0.1)
        cache.set('x', 'value')
        assert 'x' in cache
        time.sleep(0.15)
        assert 'x' not in cache

    def test_max_size_zero_raises(self):
        with pytest.raises(ValueError):
            LRUCache(max_size=0)

    def test_clear(self):
        cache = LRUCache(max_size=10)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.clear()
        assert cache.size() == 0
        assert cache.get('a') is None


# ==============================
# Config
# ==============================

class TestConfig:
    """配置加载器测试"""

    def test_default_config_has_all_sections(self):
        config = get_default_config()
        assert 'app' in config
        assert 'pdf' in config
        assert 'ocr' in config
        assert 'batch' in config
        assert 'export' in config

    def test_default_config_has_paddleocr_section(self):
        config = get_default_config()
        vl = config['ocr']['paddleocr_vl']
        assert 'vl_rec_model_name' in vl
        assert 'device' in vl
        assert 'precision' in vl
        assert 'match_iou_threshold' in vl

    def test_default_config_has_rapidocr_section(self):
        config = get_default_config()
        rapid = config['ocr']['rapidocr']
        assert 'use_gpu' in rapid
        assert 'lang' in rapid

    def test_env_var_override(self):
        os.environ['PDFOCR_ENGINE'] = 'rapidocr'
        config = get_default_config()
        config['ocr']['engine'] = 'paddleocr_vl'  # 模拟配置文件值
        # load_config 会检查环境变量
        from app.utils.config_loader import load_config
        config2 = load_config()
        assert config2['ocr']['engine'] == 'rapidocr'
        del os.environ['PDFOCR_ENGINE']
