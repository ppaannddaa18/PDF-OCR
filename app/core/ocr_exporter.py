"""OCR 结果导出：TXT / Markdown / JSON（含块坐标结构）"""
import json
import re
from pathlib import Path
from typing import List
from app.models.page_result import PageResult


def _page_text(result: PageResult) -> str:
    """markdown 去标记 → 纯文本（标题行整行剔除；列表/引用只剥行首标记）

    只剔除行首 markdown 语法（`- `、`* `、`+ `、`> `、标题行整行），正文中的
    `-`/`#`/`*`/`` ` ``/`~` 等字符原样保留——日期（2024-08-15）、编号
    （1234-5678）、代码符号（C# 语言）不被破坏。
    """
    text = result.markdown or ""
    kept = []
    for line in text.splitlines():
        if re.match(r"^\s*#+(?=\s|$)", line):
            continue
        kept.append(re.sub(r"^\s*(?:[-*+]\s|>\s)", "", line))
    return "\n".join(kept).strip()


def export_txt(pages: List[PageResult], out_dir: str, base_name: str) -> List[str]:
    written = []
    for i, page in enumerate(pages, start=1):
        path = Path(out_dir) / f"{base_name}_p{i}.txt"
        path.write_text(_page_text(page), encoding="utf-8")
        written.append(str(path))
    return written


def export_markdown(pages: List[PageResult], out_dir: str,
                    base_name: str) -> List[str]:
    parts = [f"<!-- {base_name} -->"]
    for i, page in enumerate(pages, start=1):
        parts.append(f"\n## 第 {i} 页\n\n{page.markdown or ''}")
    path = Path(out_dir) / f"{base_name}.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return [str(path)]


def export_json(pages: List[PageResult], out_dir: str,
                base_name: str) -> List[str]:
    written = []
    for i, page in enumerate(pages, start=1):
        path = Path(out_dir) / f"{base_name}_p{i}.json"
        path.write_text(json.dumps(page.raw_json, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        written.append(str(path))
    return written
