"""PaddleOCR-VL 引擎测试：官方管线整页 Spotting 组装（mock PaddleOCRVL.predict）"""
import os
import sys
import types

import numpy as np
import pytest
from PIL import Image

from app.core.ocr_engine_paddle_vl import PaddleOCRVLEngine, _json_safe

# 隔离真实 paddle/paddleocr/paddlex：unload/reset_instance 路径的
# ``import paddle`` 若命中真实包会初始化 CUDA 上下文并加载整条依赖栈
# （内存暴涨，实测 16GB 卡死）。占位空模块 → unload 内 AttributeError
# 被引擎 try/except 吞掉，测试全程零真实导入。
_REAL_PACKAGES = ("paddle", "paddleocr", "paddlex",
                  "paddlex.inference", "paddlex.inference.pipelines",
                  "paddlex.inference.pipelines.paddleocr_vl")


@pytest.fixture(autouse=True)
def _no_real_paddle(monkeypatch):
    for name in _REAL_PACKAGES:
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))


def _poly(x1, y1, x2, y2):
    """四点像素坐标（rec_polys 格式，官方整页坐标）"""
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _spot_res(pairs):
    """构造 spotting_res dict：[(text, (x1,y1,x2,y2)), ...]"""
    return {
        "rec_texts": [t for t, _ in pairs],
        "rec_polys": [_poly(*b) for _, b in pairs],
    }


class _FakeGenConfig:
    """模拟 paddlex infer.generation_config（官方默认 repetition_penalty=1.0）"""
    repetition_penalty = 1.0


class _FakePipe:
    """mock paddleocr.PaddleOCRVL：predict 返回构造结果列表（官方返回 list）。

    paddlex_pipeline.vl_rec_model.infer.generation_config 嵌套模拟生产对象图：
    真实 PaddleOCRVL 无 infer 属性，管线对象挂在 paddlex_pipeline 下
    （_pipelines/base.py:67），与引擎 _cast_params_to_bf16 等既有路径一致。
    """

    def __init__(self, results, error=None, captured=None):
        self._results = results
        self._error = error
        self.captured = captured if captured is not None else {}
        self.predict_calls = []
        self.paddlex_pipeline = types.SimpleNamespace(
            vl_rec_model=types.SimpleNamespace(
                infer=types.SimpleNamespace(
                    generation_config=_FakeGenConfig())))

    @property
    def results(self):
        """predict 返回列表（raw_json 测试用：构造后可再赋值覆盖）"""
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def predict(self, arr, **kwargs):
        self.predict_calls.append((arr, kwargs))
        self.captured.update(kwargs)
        if self._error is not None:
            raise self._error
        return self._results


class _FakeBlock:
    """带 block_label/content 的假解析块（markdown_ignore_labels 过滤用）"""

    def __init__(self, block_label, content):
        self.block_label = block_label
        self.content = content


class _FakeBlockReal:
    """带 label/content/bbox 的假解析块（真实 paddlex 3.7.2 属性名）"""

    def __init__(self, label, content, bbox=None):
        self.label = label
        self.content = content
        self.bbox = bbox if bbox is not None else [0, 0, 0, 0]


def _make_engine(pipe):
    eng = PaddleOCRVLEngine({})
    eng._initialized = True
    eng._pipe = pipe
    return eng


# ── recognize_page_auto：spotting 组装 ───────────────────────

def test_recognize_page_auto_blocks_and_line_boxes():
    pipe = _FakePipe([{
        "spotting_res": _spot_res([
            ("报关单号：090820241000039736", (100, 200, 500, 240)),
            ("价税合计：100.00", (100, 300, 400, 330)),
        ]),
        "parsing_res_list": [],
    }])
    eng = _make_engine(pipe)
    img = Image.new("RGB", (1000, 800), "white")
    result = eng.recognize_page_auto(img)
    assert len(result.blocks) == 2
    assert result.line_boxes == result.blocks
    assert result.markdown == "报关单号：090820241000039736\n价税合计：100.00"
    b = result.blocks[0]
    assert b.content == "报关单号：090820241000039736"
    # 四点→矩形：官方 rec_polys 已是整页像素坐标，直接外接
    assert b.bbox == [100.0, 200.0, 500.0, 240.0]
    assert result.image_size == (1000, 800)


def test_recognize_page_auto_spotting_call_params():
    """整页 Spotting：use_layout_detection=False + prompt_label='spotting' + max_new_tokens"""
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng = _make_engine(pipe)
    eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    _arr, kwargs = pipe.predict_calls[0]
    assert kwargs["use_layout_detection"] is False
    assert kwargs["prompt_label"] == "spotting"
    assert kwargs["max_new_tokens"] == 4096
    assert kwargs["use_doc_orientation_classify"] is False
    assert kwargs["use_doc_unwarping"] is False


def test_recognize_page_auto_poly_to_rect():
    """非轴对齐四点 → 外接矩形"""
    pipe = _FakePipe([{
        "spotting_res": {
            "rec_texts": ["倾斜文本"],
            "rec_polys": [[[50, 60], [150, 30], [180, 90], [80, 120]]],
        },
        "parsing_res_list": [],
    }])
    eng = _make_engine(pipe)
    result = eng.recognize_page_auto(Image.new("RGB", (200, 200), "white"))
    assert result.blocks[0].bbox == [50.0, 30.0, 180.0, 120.0]


def test_recognize_page_auto_skips_bad_poly():
    """单行坐标损坏不影响其余行"""
    pipe = _FakePipe([{
        "spotting_res": {
            "rec_texts": ["坏行", "好行"],
            "rec_polys": [[[1, 2], [3]], _poly(0, 0, 10, 10)],
        },
        "parsing_res_list": [],
    }])
    eng = _make_engine(pipe)
    result = eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    assert [b.content for b in result.blocks] == ["好行"]


def test_recognize_page_auto_fallback_pure_text():
    """无坐标 → parsing_res_list 文本回退（blocks 空，文本仍可用）"""
    block = types.SimpleNamespace(content="纯文本输出：报关单号 0908")
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": [block]}])
    eng = _make_engine(pipe)
    result = eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    assert result.blocks == []
    assert result.line_boxes == []
    assert result.markdown == "纯文本输出：报关单号 0908"


def test_recognize_page_auto_empty_output_raises():
    eng = _make_engine(_FakePipe([]))
    with pytest.raises(RuntimeError):
        eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))


def test_recognize_page_auto_predict_error_propagates():
    eng = _make_engine(_FakePipe([], error=RuntimeError("cuda oom")))
    with pytest.raises(RuntimeError, match="cuda oom"):
        eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))


def test_predict_once_error_dict_raises(monkeypatch):
    """官方 check_model_settings_valid 失败（如管线未加载 DocPreprocessor 却开启
    方向/扭曲矫正）→ predict_iter 仅 yield error dict 不抛异常 → 引擎转抛
    RuntimeError（防每页静默空结果）"""
    _install_fake_env(monkeypatch)
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({})
    eng._pipe = _FakePipe(
        [{"error": "the input params for model settings are invalid!"}])
    eng._initialized = True
    with pytest.raises(RuntimeError,
                       match=r"PaddleOCR-VL 推理失败: the input params"):
        eng._predict_once(Image.new("RGB", (100, 100), "white"), "spotting", None)
    PaddleOCRVLEngine.reset_instance()


def test_recognize_page_auto_error_dict_raises():
    """error dict 沿 recognize_page_auto 上抛 → 调用方转失败页占位（非空结果）"""
    pipe = _FakePipe([{"error": "the input params for model settings are invalid!"}])
    eng = _make_engine(pipe)
    with pytest.raises(RuntimeError, match="PaddleOCR-VL 推理失败"):
        eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))


def test_predict_once_error_dict_in_list_raises():
    """error dict 出现在结果列表（非首个）同样被检出；首个错误即上抛"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({})
    eng._pipe = _FakePipe([
        {"error": "model settings invalid"},
        {"spotting_res": {"rec_texts": ["ok"], "rec_polys": []}},
    ])
    eng._initialized = True
    with pytest.raises(RuntimeError, match="model settings invalid"):
        eng._predict_once(Image.new("RGB", (100, 100), "white"), "spotting", None)
    PaddleOCRVLEngine.reset_instance()


# ── recognize：单图（Region 裁剪） ───────────────────────────

def test_recognize_ocr_mode():
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": [
        types.SimpleNamespace(content="第一行"),
        types.SimpleNamespace(content="第二行"),
    ]}])
    eng = _make_engine(pipe)
    text, conf = eng.recognize(Image.new("RGB", (100, 100), "white"))
    assert text == "第一行\n第二行"
    assert conf > 0
    assert pipe.predict_calls[0][1]["prompt_label"] == "ocr"


def test_recognize_detection_mode_uses_spotting():
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng = _make_engine(pipe)
    eng.recognize(Image.new("RGB", (100, 100), "white"), mode="detection")
    assert pipe.predict_calls[0][1]["prompt_label"] == "spotting"


# ── 配置与生命周期 ───────────────────────────────────────────

def test_engine_name_and_config_defaults():
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({})
    assert eng.engine_name == "paddle_vl"
    assert eng._max_new_tokens == 4096  # 生成上限（防重复循环跑满）
    assert eng._repetition_penalty == 1.1  # 默认注入重复惩罚
    assert eng._spotting_max_pixels == 1048576  # 8GB 卡适配默认
    assert not eng.is_ready
    PaddleOCRVLEngine.reset_instance()


def test_spotting_max_pixels_config():
    """配置：1605632 → 官方默认不 patch；0 → 默认适配值"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"spotting_max_pixels": 1605632}}})
    assert eng._spotting_max_pixels == 1605632
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"spotting_max_pixels": 0}}})
    assert eng._spotting_max_pixels == 1048576
    PaddleOCRVLEngine.reset_instance()


def test_repetition_penalty_config():
    """配置：0/None → 禁用（greedy 官方行为）；显式值 → 生效"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 0}}})
    assert eng._repetition_penalty == 0.0
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 1.05}}})
    assert eng._repetition_penalty == 1.05
    PaddleOCRVLEngine.reset_instance()


# ── initialize：8GB 显存适配（bf16 转换 + spotting 像素 patch） ──

def _install_fake_env(monkeypatch, fp32_params=1):
    """注入 fake paddle / paddleocr / paddlex 包链，返回记录器。

    关键：paddlex 父包链必须全部 mock —— 引擎 ``import paddlex...pipeline``
    会先导入父包，若父包为真实模块会执行真实 __init__（加载 paddle/paddlenlp
    /transformers 依赖栈 → 测试进程内存暴涨甚至卡死）。
    """
    calls = {"set_default_dtype": [], "empty_cache": [], "cast": [],
             "share_data_with": []}

    class _FakeTensor:
        def _share_data_with(self, other):
            calls["share_data_with"].append(1)

    class _FakeParam:
        def __init__(self, dtype):
            self.dtype = dtype

        def cast(self, dtype):
            calls["cast"].append(dtype)
            return _FakeParam(dtype)

        def value(self):
            return types.SimpleNamespace(get_tensor=lambda: _FakeTensor())

    class FakeCuda:
        @staticmethod
        def empty_cache():
            calls["empty_cache"].append(1)

    fake_paddle = types.ModuleType("paddle")
    fake_paddle.set_default_dtype = lambda dt: calls["set_default_dtype"].append(dt)
    fake_paddle.disable_static = lambda: calls.setdefault("disable_static", 0) or calls.__setitem__("disable_static", calls["disable_static"] + 1)
    fake_paddle.device = types.SimpleNamespace(cuda=FakeCuda)
    fake_paddle.float32 = "fp32"
    fake_paddle.bfloat16 = "bf16"

    fake_paddleocr = types.ModuleType("paddleocr")
    fake_gen_cfg = types.SimpleNamespace(repetition_penalty=1.0)

    class _FakeSiglipAttn:
        def __init__(self):
            self._supports_sdpa = False

    _FakeSiglipAttn.__name__ = "SiglipAttention"  # 引擎按类名识别
    fake_attn = _FakeSiglipAttn()
    fake_infer = types.SimpleNamespace(
        parameters=lambda: (
            [_FakeParam("fp32") for _ in range(fp32_params)]
            + [_FakeParam("bf16") for _ in range(2)]
        ),
        generation_config=fake_gen_cfg,
        sublayers=lambda: [fake_attn],
    )

    class FakePaddleOCRVL:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.paddlex_pipeline = types.SimpleNamespace(
                vl_rec_model=types.SimpleNamespace(infer=fake_infer))

    fake_paddleocr.PaddleOCRVL = FakePaddleOCRVL

    # paddlex 包链全 mock（含父包），杜绝真实 paddlex/paddle 依赖栈导入
    for name in ("paddlex", "paddlex.inference", "paddlex.inference.pipelines",
                 "paddlex.inference.pipelines.paddleocr_vl"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    fake_vlp = types.ModuleType("paddlex.inference.pipelines.paddleocr_vl.pipeline")

    class PipelineImplClass:
        pass

    fake_vlp._PaddleOCRVLPipeline = PipelineImplClass
    fake_vlp.PaddleOCRVLPipeline = PipelineImplClass  # __init__.py 从 .pipeline 导入
    fake_vlp.tokenize_figure_of_table = lambda *a, **k: (None, {}, [])
    fake_vlp.crop_margin = lambda img: img
    fake_vlp.pre_process_for_spotting = lambda img: img

    monkeypatch.setitem(sys.modules, "paddle", fake_paddle)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_paddleocr)
    monkeypatch.setitem(
        sys.modules, "paddlex.inference.pipelines.paddleocr_vl.pipeline",
        fake_vlp)
    return calls, FakePaddleOCRVL, PipelineImplClass, fake_gen_cfg, fake_attn


def test_initialize_sets_env_and_pipeline(monkeypatch):
    """initialize：env flags + set_default_dtype + bf16 转换 + 各 patch + empty_cache"""
    PaddleOCRVLEngine.reset_instance()
    monkeypatch.delenv("FLAGS_allocator_strategy", raising=False)

    calls, FakePaddleOCRVL, PipelineImplClass, fake_gen_cfg, fake_attn = (
        _install_fake_env(monkeypatch, fp32_params=3))

    eng = PaddleOCRVLEngine({})
    eng.initialize()
    assert eng.is_ready
    assert calls["set_default_dtype"] == ["bfloat16"]
    # 3 个 fp32 参数 → cast('bf16') 3 次 + share_data_with 3 次
    assert calls["cast"] == ["bf16", "bf16", "bf16"]
    assert len(calls["share_data_with"]) == 3
    assert calls["empty_cache"] == [1]
    assert os.environ.get("FLAGS_allocator_strategy") == "auto_growth"
    assert isinstance(eng._pipe, FakePaddleOCRVL)
    assert eng._pipe.kwargs["pipeline_version"] == "v1.6"
    assert eng._pipe.kwargs["vl_rec_backend"] == "native"
    assert eng._pipe.kwargs["use_doc_orientation_classify"] is False
    assert eng._pipe.kwargs["use_doc_unwarping"] is False
    # spotting 像素上限 patch 已安装（官方 1605632 → 1048576）+ 双入口 + assemble 合并
    assert hasattr(PipelineImplClass, "_paddleocr_vl_collect_page_vlm_entries_core")
    assert hasattr(PipelineImplClass, "_paddleocr_vl_collect_block_vlm_inputs")
    assert hasattr(PipelineImplClass, "_paddleocr_vl_assemble_parsing_results")
    # 统一 collect：非 image 块 → spotting + 默认像素 1048576
    collect = PipelineImplClass._paddleocr_vl_collect_page_vlm_entries_core
    blocks = [{"img": np.zeros((100, 100, 3), dtype=np.uint8),
               "label": "text", "box": [0, 0, 100, 100]}]
    entries, has_spot, _drops = collect(None, 0, blocks, [[]],
                                        {"image_labels": ["image"]})
    assert has_spot is True
    assert entries[0][3] == "Spotting:"
    assert entries[0][4] == (112896, 1048576)
    # 重复抑制已改为 predict 前注入：initialize 不再写 generation_config
    # （保持官方 1.0，注入行为由 test_predict_once_injects_* 覆盖）
    assert fake_gen_cfg.repetition_penalty == 1.0
    # 视觉注意力 SDPA 启用（默认）
    assert fake_attn._supports_sdpa is True
    PaddleOCRVLEngine.reset_instance()


def test_initialize_keeps_official_pixels(monkeypatch):
    """配置 spotting_max_pixels=1605632 → collect 仍安装（统一标签改写必需），
    但像素保持官方值（不降上限）"""
    PaddleOCRVLEngine.reset_instance()
    _calls, _pipe_cls, PipelineImplClass, _gc, _attn = _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine(
        {"ocr": {"paddle_vl": {"spotting_max_pixels": 1605632}}})
    eng.initialize()
    assert hasattr(PipelineImplClass, "_paddleocr_vl_collect_page_vlm_entries_core")
    collect = PipelineImplClass._paddleocr_vl_collect_page_vlm_entries_core
    blocks = [{"img": np.zeros((100, 100, 3), dtype=np.uint8),
               "label": "text", "box": [0, 0, 100, 100]}]
    entries, _has_spot, _drops = collect(None, 0, blocks, [[]],
                                         {"image_labels": ["image"]})
    assert entries[0][4] == (112896, 1605632)  # 官方像素
    PaddleOCRVLEngine.reset_instance()


def test_repetition_penalty_disabled(monkeypatch):
    """配置 repetition_penalty=0 → generation_config 保持 1.0（官方 greedy）"""
    PaddleOCRVLEngine.reset_instance()
    _calls, _pipe_cls, _pipeline_cls, fake_gen_cfg, _attn = _install_fake_env(
        monkeypatch)
    eng = PaddleOCRVLEngine(
        {"ocr": {"paddle_vl": {"repetition_penalty": 0}}})
    eng.initialize()
    assert eng.is_ready
    assert fake_gen_cfg.repetition_penalty == 1.0  # 未被修改
    PaddleOCRVLEngine.reset_instance()


def test_vision_sdpa_disabled(monkeypatch):
    """配置 vision_sdpa=0 → 视觉注意力保持 eager（_supports_sdpa 不设置）"""
    PaddleOCRVLEngine.reset_instance()
    _calls, _pipe_cls, _pipeline_cls, _gc, fake_attn = _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine(
        {"ocr": {"paddle_vl": {"vision_sdpa": 0}}})
    assert eng._vision_sdpa is False
    eng.initialize()
    assert eng.is_ready
    assert fake_attn._supports_sdpa is False  # 未被启用
    PaddleOCRVLEngine.reset_instance()


def test_initialize_failure_records_error(monkeypatch):
    PaddleOCRVLEngine.reset_instance()
    fake_paddle = types.ModuleType("paddle")
    fake_paddle.set_default_dtype = lambda dt: None
    fake_paddle.device = types.SimpleNamespace(
        cuda=types.SimpleNamespace(empty_cache=lambda: None))
    fake_paddleocr = types.ModuleType("paddleocr")

    class FakePaddleOCRVL:
        def __init__(self, **kwargs):
            raise RuntimeError("模型加载失败")

    fake_paddleocr.PaddleOCRVL = FakePaddleOCRVL
    monkeypatch.setitem(sys.modules, "paddle", fake_paddle)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_paddleocr)

    eng = PaddleOCRVLEngine({})
    eng.initialize()
    assert not eng.is_ready
    assert "模型加载失败" in eng.init_error
    PaddleOCRVLEngine.reset_instance()


# ── OOM 自愈 ─────────────────────────────────────────────────

def test_predict_one_oom_retries(monkeypatch):
    """OOM → 重置引擎 → 重试一次成功"""
    eng = PaddleOCRVLEngine({})
    eng._initialized = True
    eng._pipe = object()
    calls = {"once": 0, "reset": 0}

    def _boom_once(img, pl, mnt):
        calls["once"] += 1
        if calls["once"] == 1:
            raise RuntimeError(
                "Out of memory error on GPU 0. Cannot allocate 18MB...")
        return {"spotting_res": {"rec_texts": ["重试成功"],
                                 "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]}}

    eng._predict_once = _boom_once
    eng._hard_reset = lambda: calls.__setitem__("reset", calls["reset"] + 1)
    res = eng._predict_one(Image.new("RGB", (100, 100), "white"),
                           "spotting", 4096)
    assert calls["once"] == 2
    assert calls["reset"] == 1
    assert res["spotting_res"]["rec_texts"] == ["重试成功"]


def test_predict_one_oom_persistent_raises():
    """两次都 OOM → 上抛（不无限重试）"""
    eng = PaddleOCRVLEngine({})
    eng._initialized = True
    eng._pipe = object()
    calls = {"once": 0}

    def _boom(img, pl, mnt):
        calls["once"] += 1
        raise RuntimeError("Out of memory error on GPU 0")

    eng._predict_once = _boom
    eng._hard_reset = lambda: None
    with pytest.raises(RuntimeError, match="Out of memory"):
        eng._predict_one(Image.new("RGB", (100, 100), "white"), "spotting", 4096)
    assert calls["once"] == 2  # 初次 + 重试各一次


def test_predict_one_non_oom_no_retry():
    """非 OOM 异常 → 直接上抛，不重置不重试"""
    eng = PaddleOCRVLEngine({})
    eng._initialized = True
    eng._pipe = object()
    calls = {"once": 0, "reset": 0}

    def _boom(img, pl, mnt):
        calls["once"] += 1
        raise RuntimeError("cuda oom: bad alloc")  # 不含 OOM 关键标记

    eng._predict_once = _boom
    eng._hard_reset = lambda: calls.__setitem__("reset", calls["reset"] + 1)
    with pytest.raises(RuntimeError, match="bad alloc"):
        eng._predict_one(Image.new("RGB", (100, 100), "white"), "spotting", 4096)
    assert calls["once"] == 1
    assert calls["reset"] == 0


# ── block_spotting（逐块模式） ───────────────────────────────

def test_block_spotting_config():
    """block_spotting 默认关闭；配置 1 开启"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({})
    assert eng._block_spotting is False
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"block_spotting": 1}}})
    assert eng._block_spotting is True
    PaddleOCRVLEngine.reset_instance()


def test_predict_once_forces_dynamic_mode(monkeypatch):
    """跨线程修复：predict 调用线程强制 paddle.disable_static()（动态图模式）"""
    calls, _pipe_cls, _pipeline_cls, _gc, _attn = _install_fake_env(monkeypatch)
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng = _make_engine(pipe)
    eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    assert calls["disable_static"] >= 1


def test_predict_once_uses_layout_detection():
    """默认整页模式 use_layout_detection=False；block_spotting 开启 → True"""
    # 默认（整页假盒）
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng = _make_engine(pipe)
    eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    assert pipe.predict_calls[0][1]["use_layout_detection"] is False
    # 逐块模式
    pipe2 = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng2 = _make_engine(pipe2)
    eng2._block_spotting = True
    eng2.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    assert pipe2.predict_calls[0][1]["use_layout_detection"] is True


def test_assemble_merge_offsets_coords(monkeypatch):
    """assemble 合并版：块内坐标叠加块 bbox 偏移 → 整页坐标"""
    PaddleOCRVLEngine.reset_instance()
    _calls, _pipe_cls, PipelineImplClass, _gc, _attn = _install_fake_env(
        monkeypatch)
    import paddlex.inference.pipelines.paddleocr_vl.pipeline as _vlp  # fake 命中
    eng = PaddleOCRVLEngine({})
    eng._initialized = True
    eng._pipe = object()
    eng._patch_assemble_spotting_merge()
    assemble = PipelineImplClass._paddleocr_vl_assemble_parsing_results

    def _fake_spot(*a, **k):
        return "文本", {"rec_texts": ["文本"],
                        "rec_polys": [[[10, 20], [30, 20], [30, 40], [10, 40]]]}

    import unittest.mock as mock
    with mock.patch.object(_vlp, "post_process_for_spotting", _fake_spot,
                           create=True), \
         mock.patch.object(_vlp, "truncate_repetitive_content",
                           lambda s, min_count=50: s, create=True), \
         mock.patch.object(_vlp, "PaddleOCRVLBlock", types.SimpleNamespace,
                           create=True):
        blocks = [[{
            "img": np.zeros((100, 100, 3), dtype=np.uint8),
            "box": [500, 300, 600, 400],
            "label": "spotting",
        }]]
        batch = {"px": {
            "vlm_block_ids": [(0, 0)], "curr_vlm_block_idx": 0,
            "images": [None], "figure_token_maps": [{}],
            "vlm_results": [{"result": "文本<|LOC_10|>"}],
        }}
        id2px = {(0, 0): "px"}
        _res_lists, _tables, spot_list = assemble(
            None, blocks, batch, id2px, set(), ["image"])
    assert spot_list[0]["rec_texts"] == ["文本"]
    # 块内 (10,20) + 偏移 (500,300) → 整页 (510,320)
    assert spot_list[0]["rec_polys"] == [
        [[510.0, 320.0], [530.0, 320.0], [530.0, 340.0], [510.0, 340.0]]]
    PaddleOCRVLEngine.reset_instance()


# ── 解析配置透传 + 重复抑制热注入 ────────────────────────────

def test_predict_once_passes_parse_config_kwargs(monkeypatch):
    """解析配置透传：方向/扭曲矫正等 kwargs 来自配置（不再硬编码 False）"""
    PaddleOCRVLEngine.reset_instance()
    _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "use_ocr_for_image_block": False,
        "merge_layout_blocks": False,
        "spotting_min_pixels": 256,
    }}})
    captured = {}
    eng._pipe = _FakePipe(
        [{"spotting_res": {}, "parsing_res_list": []}], captured=captured)
    eng._initialized = True
    eng._predict_once(Image.new("RGB", (100, 100), "white"), "spotting", None)
    assert captured["use_doc_orientation_classify"] is True
    assert captured["use_doc_unwarping"] is True
    assert captured["use_chart_recognition"] is False
    assert captured["use_seal_recognition"] is False
    assert captured["use_ocr_for_image_block"] is False
    assert captured["merge_layout_blocks"] is False
    PaddleOCRVLEngine.reset_instance()


def test_predict_once_injects_repetition_penalty_each_call(monkeypatch):
    """重复抑制每次 predict 前注入 generation_config（热生效，生产对象图路径）"""
    PaddleOCRVLEngine.reset_instance()
    _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 1.5}}})
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng._pipe = pipe
    eng._initialized = True
    eng._repetition_penalty = 1.5  # 模拟配置已改
    eng._predict_once(Image.new("RGB", (100, 100), "white"), "spotting", None)
    assert pipe.paddlex_pipeline.vl_rec_model.infer.\
        generation_config.repetition_penalty == 1.5
    PaddleOCRVLEngine.reset_instance()


def test_predict_once_skips_injection_when_penalty_disabled(monkeypatch):
    """repetition_penalty=0/None/1.0 → 不写入，generation_config 保持官方 1.0
    （生成链仅 penalty!=1.0 时构造 RepetitionPenaltyLogitsProcessor，
    penalty=0 会抛 ValueError）"""
    PaddleOCRVLEngine.reset_instance()
    _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 0}}})
    pipe = _FakePipe([{"spotting_res": {}, "parsing_res_list": []}])
    eng._pipe = pipe
    eng._initialized = True
    eng._predict_once(Image.new("RGB", (100, 100), "white"), "spotting", None)
    assert pipe.paddlex_pipeline.vl_rec_model.infer.\
        generation_config.repetition_penalty == 1.0
    PaddleOCRVLEngine.reset_instance()


# ── 辅助内容过滤（markdown_ignore_labels） ───────────────────

def test_markdown_ignore_labels_filters_parsing_blocks():
    """辅助内容过滤：block_label 命中 ignore 集的块从 markdown/raw 剔除"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "markdown_ignore_labels": ["header", "footer"]}}})
    res = {
        "parsing_res_list": [
            _FakeBlock("header", "Hindawi Journal"),
            _FakeBlock("paragraph", "Body text here"),
            _FakeBlock("footer", "Copyright 2017"),
        ],
        "spotting_res": {"rec_texts": [], "rec_polys": []},
    }
    filtered = eng._filter_ignored_blocks(res)
    labels = [b.block_label for b in filtered["parsing_res_list"]]
    assert labels == ["paragraph"]
    # 原结果不被就地修改（浅拷贝语义）
    assert [b.block_label for b in res["parsing_res_list"]] == [
        "header", "paragraph", "footer"]
    PaddleOCRVLEngine.reset_instance()


def test_markdown_ignore_labels_filters_real_attr_blocks():
    """真实属性名（label/content/bbox）：label 命中 ignore 集的块被剔除"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "markdown_ignore_labels": ["header", "number"]}}})
    res = {
        "parsing_res_list": [
            _FakeBlockReal("header", "Hindawi Journal"),
            _FakeBlockReal("paragraph", "Body text here"),
            _FakeBlockReal("number", "Page 42"),
        ],
        "spotting_res": {"rec_texts": [], "rec_polys": []},
    }
    filtered = eng._filter_ignored_blocks(res)
    assert [b.label for b in filtered["parsing_res_list"]] == ["paragraph"]
    # 原结果不被就地修改（浅拷贝语义）
    assert [b.label for b in res["parsing_res_list"]] == [
        "header", "paragraph", "number"]
    PaddleOCRVLEngine.reset_instance()


def test_ignore_labels_default_empty():
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {}}})
    assert eng._markdown_ignore_labels == []
    PaddleOCRVLEngine.reset_instance()


# ── 配置热生效（apply_config，解析配置弹窗接线） ─────────────

def test_apply_config_updates_parse_attributes():
    """I1：apply_config 全键更新——类型转换与 __init__ 一致（float/bool/int/list）"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({})
    eng.apply_config({"ocr": {"paddle_vl": {
        "repetition_penalty": 1.5,
        "markdown_ignore_labels": ["header", "footer"],
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "use_ocr_for_image_block": False,
        "merge_layout_blocks": False,
        "spotting_min_pixels": 256,
        "spotting_max_pixels": 1605632,
        "block_spotting": True,
    }}})
    assert eng._repetition_penalty == 1.5
    assert eng._markdown_ignore_labels == ["header", "footer"]
    assert eng._use_doc_orientation_classify is True
    assert eng._use_doc_unwarping is True
    assert eng._use_chart_recognition is False
    assert eng._use_seal_recognition is False
    assert eng._use_ocr_for_image_block is False
    assert eng._merge_layout_blocks is False
    assert eng._spotting_min_pixels == 256
    assert eng._spotting_max_pixels == 1605632
    assert eng._block_spotting is True
    PaddleOCRVLEngine.reset_instance()


def test_apply_config_missing_keys_unchanged():
    """I1：缺失键保持不变；spotting_max_pixels=0 → 默认适配值（同 __init__）"""
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "repetition_penalty": 1.1, "block_spotting": True}}})
    eng.apply_config({"ocr": {"paddle_vl": {
        "repetition_penalty": 0.0, "spotting_max_pixels": 0}}})
    assert eng._repetition_penalty == 0.0
    assert eng._spotting_max_pixels == 1048576
    assert eng._block_spotting is True          # 缺失键不变
    assert eng._use_doc_orientation_classify is False
    assert eng._markdown_ignore_labels == []
    assert eng._spotting_min_pixels == 0
    PaddleOCRVLEngine.reset_instance()


def test_apply_config_empty_patch_noop():
    PaddleOCRVLEngine.reset_instance()
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 1.1}}})
    eng.apply_config({})
    assert eng._repetition_penalty == 1.1
    PaddleOCRVLEngine.reset_instance()


# ── _collect 辅助内容过滤（逐块模式识别前剔除） ──────────────

def test_collect_filters_ignored_labels_before_vlm(monkeypatch):
    """I2：逐块模式辅助内容过滤——ignore 标签块识别前剔除（不进 vlm_entries）

    assemble 阶段标签已被改写为 "spotting"，_filter_ignored_blocks（按原
    标签）永不命中 → 必须在 _collect 改写前过滤。整页假盒 label "spotting"
    不在忽略集，不受影响。过滤集合每次调用从引擎实例读取 → apply_config
    热生效（无需重装 patch）。
    """
    PaddleOCRVLEngine.reset_instance()
    _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "markdown_ignore_labels": ["header"]}}})
    eng._patch_spotting_max_pixels()
    import paddlex.inference.pipelines.paddleocr_vl.pipeline as _vlp
    collect = _vlp._PaddleOCRVLPipeline._paddleocr_vl_collect_page_vlm_entries_core
    blocks = [
        {"img": np.zeros((30, 100, 3), dtype=np.uint8),
         "label": "header", "box": [0, 0, 100, 30]},
        {"img": np.zeros((100, 100, 3), dtype=np.uint8),
         "label": "paragraph", "box": [0, 30, 100, 130]},
    ]
    entries, has_spot, _drops = collect(None, 0, blocks, [[]],
                                        {"image_labels": ["image"]})
    assert len(entries) == 1                      # 只剩 paragraph 块进 VLM
    assert entries[0][1] == 1
    assert blocks[0]["label"] == "header"         # 忽略块未被改写/未送 VLM
    assert blocks[1]["label"] == "spotting"
    assert has_spot is True
    # 热生效：apply_config 追加忽略标签 → 再次 collect 也剔除
    eng.apply_config({"ocr": {"paddle_vl": {
        "markdown_ignore_labels": ["header", "paragraph"]}}})
    blocks2 = [
        {"img": np.zeros((30, 100, 3), dtype=np.uint8),
         "label": "header", "box": [0, 0, 100, 30]},
        {"img": np.zeros((100, 100, 3), dtype=np.uint8),
         "label": "paragraph", "box": [0, 30, 100, 130]},
    ]
    entries2, _hs2, _dr2 = collect(None, 0, blocks2, [[]],
                                   {"image_labels": ["image"]})
    assert len(entries2) == 0
    PaddleOCRVLEngine.reset_instance()


# ── raw_json 填充（JSON 视图/导出数据源） ─────────────────────

def test_recognize_page_auto_fills_raw_json(monkeypatch):
    """raw_json 填充：包含 parsing_res_list 且可 JSON 序列化"""
    _install_fake_env(monkeypatch)
    eng = PaddleOCRVLEngine({})
    eng._pipe = _FakePipe({})
    eng._initialized = True
    eng._pipe.results = [{"parsing_res_list": [_FakeBlock("paragraph", "hi")],
                          "spotting_res": {"rec_texts": ["hi"],
                                           "rec_polys": [[[0, 0], [1, 0],
                                                          [1, 1], [0, 1]]]}}]
    page = eng.recognize_page_auto(Image.new("RGB", (100, 100), "white"))
    import json
    json.dumps(page.raw_json)  # 必须可序列化
    assert page.raw_json["spotting_res"]["rec_texts"] == ["hi"]
    assert page.raw_json["parsing_res_list"][0]["block_label"] == "paragraph"
    PaddleOCRVLEngine.reset_instance()


def test_json_safe_large_array_degraded():
    """大数组 ((100,100,3) uint8, 30000 元素 > 阈值) → 降级为紧凑描述"""
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    out = _json_safe(arr)
    import json
    json.dumps(out)  # 仍可 JSON 序列化
    assert out == {"__ndarray__": [100, 100, 3], "dtype": "uint8"}


def test_json_safe_spotting_shape_array_kept():
    """典型 spotting 坐标形状 (300,4,2) float32（2400 元素 ≤ 阈值）→ tolist() 保留"""
    arr = np.zeros((300, 4, 2), dtype=np.float32)
    out = _json_safe(arr)
    assert isinstance(out, list) and len(out) == 300
    assert len(out[0]) == 4 and len(out[0][0]) == 2


def test_json_safe_real_block_to_official_dict():
    """真实属性名块（label/content/bbox）→ 官方 _to_json 结构字典"""
    b = _FakeBlockReal("paragraph", "hi", bbox=[0, 0, 100, 50])
    out = _json_safe(b)
    import json
    json.dumps(out)  # 必须可序列化
    assert out == {"block_label": "paragraph",
                   "block_content": "hi",
                   "block_bbox": [0, 0, 100, 50]}


def test_json_safe_legacy_block_label_fallback():
    """旧属性块（仅 block_label）：label 缺失 → block_label 兜底，bbox 缺省 []"""
    b = _FakeBlock("header", "legacy")
    out = _json_safe(b)
    assert out == {"block_label": "header",
                   "block_content": "legacy",
                   "block_bbox": []}
