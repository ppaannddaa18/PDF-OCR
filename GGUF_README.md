# PaddleOCR-VL GGUF 模型使用指南

## 文件说明

| 文件 | 说明 |
|------|------|
| `models/PaddleOCR-VL-1.6-GGUF.gguf` | 主模型文件 (892.4 MB) |
| `models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf` | 视觉投影模型 (840.9 MB) |
| `llama-b9969/llama-server.exe` | llama.cpp 服务器（从 llama.cpp Releases 下载 CUDA 版，连同 DLL 解压到 `llama-b9969/`） |
| `start_llama_server.bat` | 手动启动脚本（应用内一般由引擎自动托管） |
| `gguf_guide.py` | 部署说明与手动 HTTP 调用示例 |

## 使用步骤

### 1. 启动 llama-server

应用内由 `ocr_engine_gguf.py` 自动托管启动/停止；如需手动验证，双击运行
`start_llama_server.bat` 或在命令行中执行：

```bash
llama-b9969\llama-server.exe -m models/PaddleOCR-VL-1.6-GGUF.gguf --mmproj models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf --port 9999 --temp 0.2 -n 2048
```

服务启动后，会显示类似信息：
```
llama server listening at http://127.0.0.1:9999
```

### 2. 运行 OCR 测试

在另一个命令行窗口中查看部署说明：

```bash
python gguf_guide.py
```

### 3. 在代码中使用

```python
from app.core.ocr_engine_gguf import GGUFOCREngine

# 应用内直接使用引擎（自动启动/停止 llama-server）：
engine = GGUFOCREngine(config)
engine.initialize()
page_result = engine.recognize_page_auto(image)
print(page_result.markdown)
```

## API 端点

llama-server 提供 OpenAI 兼容的 API：

- **URL**: `http://127.0.0.1:9999/v1/chat/completions`
- **Method**: POST
- **Content-Type**: application/json

### 请求示例

```json
{
  "model": "PaddleOCR-VL-1.6",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "OCR:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
      ]
    }
  ],
  "temperature": 0.0,
  "max_tokens": 2048
}
```

## 显存需求

| 模型 | 显存需求 |
|------|---------|
| PaddleOCR-VL-1.6-GGUF（模型文件） | ~1.7 GB |
| 推理时（8GB 显存实测） | ~4–5 GB |

相比原始 PaddleOCR-VL (需要 8GB+)，GGUF 版本可以在 8GB 显存上正常运行。

## 优势

1. **显存占用低**: 仅需 4-5GB，适合 RTX 5060 等 8GB 显卡
2. **启动速度快**: 无需等待模型编译
3. **独立服务**: 可以作为独立服务运行，方便集成
4. **跨平台**: 支持 Windows、Linux、macOS

## 注意事项

1. llama-server 需要保持运行，不能关闭窗口
2. 首次加载模型需要几秒钟时间
3. 图像是通过 base64 编码传输的，大图像会占用较多内存
4. 图像按 `min_pixels`/`max_pixels` 自动缩放（默认约 146K~2.8M 像素），无需手动裁剪

## 故障排除

### 问题: llama-server 无法启动

**解决**: 确保所有 DLL 文件在同一目录：
- `ggml.dll`
- `ggml-base.dll`
- `ggml-cpu.dll`
- `llama.dll`

### 问题: 连接被拒绝

**解决**: 
1. 检查 llama-server 是否已启动
2. 检查防火墙设置
3. 确认端口 9999 未被占用（可在模型设置页修改）

### 问题: OCR 结果为空

**解决**:
1. 检查图像路径是否正确
2. 检查 base64 编码是否正确
3. 尝试使用不同的 prompt（模型设置页切换 prompt_type），或调高 max_tokens（默认 2048）
