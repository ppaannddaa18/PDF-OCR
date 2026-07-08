"""TableExtractor — 从 Markdown 文本中提取表格为 DataFrame"""
from typing import List
import re
import logging
from io import StringIO
import pandas as pd

logger = logging.getLogger("PDFOCR")

# 匹配 Markdown 表格行（以 | 开头和结尾的行）
_TABLE_ROW_RE = re.compile(r'^\s*\|.+\|\s*$', re.MULTILINE)
# 匹配表格分隔符行（如 |---|---|）
_TABLE_SEP_RE = re.compile(r'^\|?[\s\-:|]+\|?$')


def extract_tables(markdown: str) -> List[pd.DataFrame]:
    """
    从 Markdown 中提取所有表格为 DataFrame 列表。
    解析失败时保留原始文本在 meta 中，不抛异常。

    Args:
        markdown: 整页 Markdown 文本

    Returns:
        DataFrame 列表（可能为空）
    """
    tables = []
    lines = markdown.split('\n')
    i = 0
    while i < len(lines):
        # 找表格起始行：非分隔符的 |...| 行
        if not _TABLE_ROW_RE.match(lines[i]):
            i += 1
            continue
        if _TABLE_SEP_RE.match(lines[i]):
            i += 1
            continue

        # 收集连续表格行
        table_lines = []
        while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
            table_lines.append(lines[i])
            i += 1

        if len(table_lines) < 2:
            continue

        # 过滤掉分隔符行
        data_lines = [l for l in table_lines if not _TABLE_SEP_RE.match(l)]
        if len(data_lines) < 2:
            continue

        try:
            # 清洗并解析
            cleaned = '\n'.join(data_lines)
            df = pd.read_csv(StringIO(cleaned), sep='|', engine='python')
            # 去掉边框产生的空列（仅首尾空列，保留中间可能为空的列）
            if df.shape[1] >= 3:
                # 首列和末列是管道表的外边框，总是空的
                df = df.iloc[:, 1:-1]
            elif df.shape[1] == 2:
                df = df.iloc[:, 1:]
            if not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                tables.append(df)
        except Exception as e:
            # 解析失败：保留原始 Markdown，不搞崩整页
            logger.debug(f"TableExtractor: parse failed, keeping raw: {e}")
            df_raw = pd.DataFrame({"raw_markdown": [l.strip() for l in table_lines]})
            tables.append(df_raw)

    return tables
