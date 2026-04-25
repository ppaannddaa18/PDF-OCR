"""
识别历史记录管理
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict
from app.models.ocr_result import FileResult


@dataclass
class HistoryRecord:
    """历史记录条目"""
    id: str
    timestamp: str
    file_count: int
    success_count: int
    field_names: List[str]
    export_path: Optional[str]
    results_data: List[dict]  # 序列化的结果数据


class HistoryManager:
    """历史记录管理器（带内存缓存）"""

    HISTORY_FILE = "ocr_history.json"
    MAX_RECORDS = 10

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/.pdf_ocr_tool")
        self.storage_dir = storage_dir
        self.history_file = os.path.join(storage_dir, self.HISTORY_FILE)
        self._cached_history: Optional[List[HistoryRecord]] = None
        self._dirty = False
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_dir, exist_ok=True)

    def _load_history(self) -> List[HistoryRecord]:
        """加载历史记录到内存缓存"""
        if self._cached_history is not None:
            return self._cached_history

        if not os.path.exists(self.history_file):
            self._cached_history = []
            return self._cached_history

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cached_history = [HistoryRecord(**item) for item in data]
                return self._cached_history
        except Exception:
            self._cached_history = []
            return self._cached_history

    def _save_history(self, history: List[HistoryRecord]):
        """保存历史记录到文件"""
        self._cached_history = history
        self._dirty = True
        self._flush_to_disk()

    def _flush_to_disk(self):
        """将缓存写入磁盘"""
        if not self._dirty or self._cached_history is None:
            return
        try:
            data = [asdict(record) for record in self._cached_history]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._dirty = False
        except Exception:
            pass

    def add_record(self, results: List[FileResult], export_path: str = None) -> HistoryRecord:
        """添加新的历史记录"""
        # 序列化结果
        results_data = []
        field_names = set()
        for r in results:
            result_dict = {
                "source_file": r.source_file,
                "success": r.success,
                "error_msg": r.error_msg,
                "fields": {}
            }
            for fn, fr in r.fields.items():
                field_names.add(fn)
                result_dict["fields"][fn] = {
                    "text": fr.text,
                    "confidence": fr.confidence,
                    "manually_edited": fr.manually_edited
                }
            results_data.append(result_dict)

        # 使用微秒级时间戳避免ID冲突
        from time import time
        timestamp = datetime.now()
        record_id = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{int(time() * 1000) % 1000}"

        record = HistoryRecord(
            id=record_id,
            timestamp=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            file_count=len(results),
            success_count=sum(1 for r in results if r.success),
            field_names=list(field_names),
            export_path=export_path,
            results_data=results_data
        )

        # 读取现有历史（使用缓存）
        history = self._load_history()

        # 添加新记录到开头
        history.insert(0, record)

        # 限制记录数量
        if len(history) > self.MAX_RECORDS:
            history = history[:self.MAX_RECORDS]

        # 保存
        self._save_history(history)

        return record

    def get_history(self) -> List[HistoryRecord]:
        """获取所有历史记录"""
        return self._load_history()

    def get_record(self, record_id: str) -> Optional[HistoryRecord]:
        """获取指定记录"""
        history = self._load_history()
        for record in history:
            if record.id == record_id:
                return record
        return None

    def delete_record(self, record_id: str) -> bool:
        """删除指定记录"""
        history = self._load_history()
        history = [r for r in history if r.id != record_id]
        self._save_history(history)
        return True

    def clear_history(self):
        """清空所有历史"""
        self._save_history([])

    def restore_results(self, record_id: str) -> Optional[List[FileResult]]:
        """从历史记录恢复结果"""
        from app.models.ocr_result import FieldResult

        record = self.get_record(record_id)
        if not record:
            return None

        results = []
        for data in record.results_data:
            # 先构建 fields 字典
            fields = {}
            for fn, fd in data["fields"].items():
                field_result = FieldResult(
                    field_name=fn,
                    text=fd["text"],
                    confidence=fd["confidence"]
                )
                field_result.manually_edited = fd.get("manually_edited", False)
                fields[fn] = field_result

            # 创建 FileResult，传入所有必需参数
            file_result = FileResult(
                source_file=data["source_file"],
                fields=fields,
                success=data["success"],
                error_msg=data["error_msg"]
            )

            results.append(file_result)

        return results
