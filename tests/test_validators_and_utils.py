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

    def test_default_config_has_gguf_section(self):
        config = get_default_config()
        gguf = config['ocr']['gguf']
        assert 'server_path' in gguf
        assert 'model_path' in gguf
        assert 'mmproj_path' in gguf
        assert 'port' in gguf

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


class TestGgufPathRepair:
    """GGUF 失效路径自动修复（C:\\llama 等旧绝对路径 → 仓库内相对路径）"""

    def test_repair_replaces_broken_absolute_paths(self, monkeypatch, tmp_path):
        from app.utils import config_loader

        # 模拟仓库根目录里存在默认布局的模型文件
        fake_root = tmp_path / "repo"
        (fake_root / "llama-b9969").mkdir(parents=True)
        (fake_root / "models").mkdir()
        (fake_root / "llama-b9969" / "llama-server.exe").touch()
        (fake_root / "models" / "PaddleOCR-VL-1.6-GGUF.gguf").touch()
        (fake_root / "models" / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf").touch()
        monkeypatch.setattr(config_loader, "_project_root", lambda: fake_root)

        config = get_default_config()
        config["ocr"]["gguf"]["server_path"] = r"C:\llama\llama-server.exe"
        config["ocr"]["gguf"]["model_path"] = r"C:\models\ocr.gguf"
        config["ocr"]["gguf"]["mmproj_path"] = r"C:\models\mmproj.gguf"

        changed = config_loader._repair_gguf_paths(config)
        assert changed is True
        gguf = config["ocr"]["gguf"]
        assert gguf["server_path"] == "llama-b9969/llama-server.exe"
        assert gguf["model_path"] == "models/PaddleOCR-VL-1.6-GGUF.gguf"
        assert gguf["mmproj_path"] == "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"

    def test_repair_keeps_valid_existing_path(self, monkeypatch, tmp_path):
        from app.utils import config_loader

        fake_root = tmp_path / "repo"
        (fake_root / "models").mkdir(parents=True)
        valid = fake_root / "models" / "custom.gguf"
        valid.touch()
        monkeypatch.setattr(config_loader, "_project_root", lambda: fake_root)

        config = get_default_config()
        config["ocr"]["gguf"]["model_path"] = "models/custom.gguf"

        changed = config_loader._repair_gguf_paths(config)
        assert changed is False
        assert config["ocr"]["gguf"]["model_path"] == "models/custom.gguf"

    def test_repair_no_defaults_keeps_broken_path(self, monkeypatch, tmp_path):
        """仓库内没有默认文件时不做任何替换（保留原值，让检查器如实报告）"""
        from app.utils import config_loader

        fake_root = tmp_path / "empty-repo"
        fake_root.mkdir()
        monkeypatch.setattr(config_loader, "_project_root", lambda: fake_root)

        config = get_default_config()
        config["ocr"]["gguf"]["model_path"] = r"C:\models\ocr.gguf"

        changed = config_loader._repair_gguf_paths(config)
        assert changed is False
        assert config["ocr"]["gguf"]["model_path"] == r"C:\models\ocr.gguf"

    def test_load_config_runs_repair_pipeline(self, monkeypatch, tmp_path):
        """load_config 加载后调用修复：失效绝对路径被换成默认相对路径"""
        from app.utils import config_loader

        fake_root = tmp_path / "repo"
        (fake_root / "llama-b9969").mkdir(parents=True)
        (fake_root / "models").mkdir()
        (fake_root / "llama-b9969" / "llama-server.exe").touch()
        (fake_root / "models" / "PaddleOCR-VL-1.6-GGUF.gguf").touch()
        (fake_root / "models" / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf").touch()
        monkeypatch.setattr(config_loader, "_project_root", lambda: fake_root)

        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "ocr:\n"
            "  engine: gguf\n"
            "  gguf:\n"
            "    server_path: C:\\llama\\llama-server.exe\n"
            "    model_path: C:\\models\\ocr.gguf\n"
            "    mmproj_path: C:\\models\\mmproj.gguf\n",
            encoding="utf-8",
        )
        config = config_loader.load_config(str(cfg_file))
        gguf = config["ocr"]["gguf"]
        assert gguf["server_path"] == "llama-b9969/llama-server.exe"
        assert gguf["model_path"] == "models/PaddleOCR-VL-1.6-GGUF.gguf"
        assert gguf["mmproj_path"] == "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
