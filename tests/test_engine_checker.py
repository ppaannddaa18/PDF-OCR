"""引擎可用性检查器单元测试（Task P1）

通过 monkeypatch _get_base_dir 把 base_dir 指向临时目录，模拟文件系统布局；
RapidOCR 分支通过 monkeypatch _find_spec 隔离。
"""
from pathlib import Path

import pytest

from app.utils import engine_checker


def _gguf_config() -> dict:
    """默认 gguf 配置（相对路径，按 base_dir 解析）"""
    return {
        "ocr": {
            "engine": "gguf",
            "gguf": {
                "server_path": "llama-b9969/llama-server.exe",
                "model_path": "models/PaddleOCR-VL-1.6-GGUF.gguf",
                "mmproj_path": "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
            },
        },
    }


@pytest.fixture(autouse=True)
def _fake_base_dir(monkeypatch, tmp_path) -> Path:
    """base_dir 与 cwd 均指向临时目录（对齐 _resolve_model_path 的 base_dir→cwd 解析顺序），
    避免真实仓库根目录下的 llama-b9969/models 文件污染测试"""
    monkeypatch.setattr(engine_checker, "_get_base_dir", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_gguf_layout(base: Path, with_dll: bool = True):
    """在 base 下写入完整的默认 GGUF 文件布局"""
    (base / "llama-b9969").mkdir(parents=True)
    (base / "llama-b9969" / "llama-server.exe").touch()
    (base / "models").mkdir()
    (base / "models" / "PaddleOCR-VL-1.6-GGUF.gguf").touch()
    (base / "models" / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf").touch()
    if with_dll:
        (base / "llama-b9969" / "ggml-cuda.dll").touch()


class TestGguf:
    def test_all_missing(self, _fake_base_dir):
        """三个关键文件全缺失 → available=False，issues 逐项列出"""
        result = engine_checker.check_engine_availability(_gguf_config())
        gguf = result["gguf"]
        assert gguf["available"] is False
        assert any("llama-server.exe" in i for i in gguf["issues"])
        assert any("模型文件不存在" in i for i in gguf["issues"])
        assert any("MMProj 文件不存在" in i for i in gguf["issues"])

    def test_all_present(self, _fake_base_dir):
        """文件齐全（含 ggml-cuda.dll）→ available=True、无 issue"""
        _write_gguf_layout(_fake_base_dir)
        result = engine_checker.check_engine_availability(_gguf_config())
        assert result["gguf"] == {"available": True, "issues": []}

    def test_dll_missing_is_warning(self, _fake_base_dir):
        """server/model/mmproj 在但 ggml-cuda.dll 缺 → available 仍 True，警告级 issue"""
        _write_gguf_layout(_fake_base_dir, with_dll=False)
        result = engine_checker.check_engine_availability(_gguf_config())
        gguf = result["gguf"]
        assert gguf["available"] is True
        assert any("警告" in i and "ggml-cuda.dll" in i for i in gguf["issues"])

    def test_absolute_paths(self, tmp_path):
        """绝对路径直接按自身存在性判断（不受 base_dir 影响）"""
        server_dir = tmp_path / "srv"
        server_dir.mkdir()
        (server_dir / "llama-server.exe").touch()
        (server_dir / "ggml-cuda.dll").touch()
        (tmp_path / "m1.gguf").touch()
        (tmp_path / "m2.gguf").touch()
        config = {"ocr": {"gguf": {
            "server_path": str(server_dir / "llama-server.exe"),
            "model_path": str(tmp_path / "m1.gguf"),
            "mmproj_path": str(tmp_path / "m2.gguf"),
        }}}
        result = engine_checker.check_engine_availability(config)
        assert result["gguf"] == {"available": True, "issues": []}

    def test_missing_gguf_section_not_crash(self, _fake_base_dir):
        """config 无 ocr.gguf 段 → 不抛异常，判不可用并提示未配置"""
        result = engine_checker.check_engine_availability({})
        gguf = result["gguf"]
        assert gguf["available"] is False
        assert any("未配置" in i for i in gguf["issues"])

    def test_returns_both_engines(self, _fake_base_dir):
        result = engine_checker.check_engine_availability(_gguf_config())
        assert set(result.keys()) == {"gguf", "rapidocr"}


class TestRapidOcr:
    def test_package_missing(self, monkeypatch):
        """rapidocr_onnxruntime 不可导入 → available=False"""
        monkeypatch.setattr(engine_checker, "_find_spec", lambda name: None)
        result = engine_checker.check_engine_availability({})["rapidocr"]
        assert result["available"] is False
        assert "rapidocr_onnxruntime" in result["issues"][0]

    def test_package_present(self, monkeypatch):
        """包可导入 → available=True、无 issue"""
        class _FakeSpec:
            pass
        monkeypatch.setattr(engine_checker, "_find_spec", lambda name: _FakeSpec())
        result = engine_checker.check_engine_availability({})["rapidocr"]
        assert result["available"] is True
        assert result["issues"] == []
