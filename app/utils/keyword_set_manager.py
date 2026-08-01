"""命名关键字集管理 — JSON 持久化（镜像 HistoryManager 模式）

存储：~/.pdf_ocr_tool/keyword_sets.json（storage_dir 可注入供测试）
结构：{"集合名": ["关键字", ...], ...}；原子写（tmp + os.replace），
损坏时备份 .bak 后返回空。
"""
import json
import logging
import os
import shutil
import threading


class KeywordSetManager:
    STORE_FILE = "keyword_sets.json"

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/.pdf_ocr_tool")
        self.storage_dir = storage_dir
        self.store_file = os.path.join(storage_dir, self.STORE_FILE)
        self._lock = threading.RLock()
        os.makedirs(self.storage_dir, exist_ok=True)

    def _load_all(self) -> dict:
        if not os.path.exists(self.store_file):
            return {}
        try:
            with open(self.store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logging.getLogger("PDFOCR").warning(
                f"KeywordSetManager: 加载失败 ({e})，备份到 .bak")
            try:
                shutil.copy2(self.store_file, self.store_file + ".bak")
            except Exception:
                pass
            return {}

    def _save_all(self, data: dict):
        tmp = self.store_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.store_file)

    def list_sets(self) -> list:
        with self._lock:
            return sorted(self._load_all().keys())

    def load(self, name: str):
        with self._lock:
            return self._load_all().get(name)

    def save(self, name: str, keywords: list):
        with self._lock:
            data = self._load_all()
            data[name] = list(keywords)
            self._save_all(data)

    def delete(self, name: str) -> bool:
        with self._lock:
            data = self._load_all()
            if name not in data:
                return False
            del data[name]
            self._save_all(data)
            return True
