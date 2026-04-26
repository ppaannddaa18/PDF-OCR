"""
LRU缓存实现 - 性能优化版
- 线程安全
- 内存占用感知
- 支持过期时间
"""
from collections import OrderedDict
import threading
import time
from typing import Optional, Any, Callable


class LRUCache:
    """
    线程安全的LRU缓存实现

    优化点：
    1. 线程安全（使用RLock）
    2. 支持过期时间
    3. 支持内存占用回调
    """

    def __init__(
        self,
        max_size: int = 20,
        ttl_seconds: Optional[float] = None,
        on_evict: Optional[Callable[[str, Any], None]] = None
    ):
        """
        初始化LRU缓存

        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 过期时间（秒），None表示永不过期
            on_evict: 淘汰回调函数
        """
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._on_evict = on_evict
        self._lock = threading.RLock()
        # 存储访问时间：(value, access_time)
        self._timestamps: dict = {}

    def get(self, key, default=None):
        """获取缓存值，如果存在则更新访问顺序"""
        with self._lock:
            if key not in self._cache:
                return default

            # 检查过期
            if self._ttl is not None:
                access_time = self._timestamps.get(key, 0)
                if time.time() - access_time > self._ttl:
                    # 已过期，删除并返回默认值
                    self._remove_internal(key)
                    return default

            self._cache.move_to_end(key)
            self._timestamps[key] = time.time()
            return self._cache[key]

    def set(self, key, value):
        """设置缓存值，如果超过容量则淘汰最久未使用的"""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._max_size:
                    self._evict_one()

            self._cache[key] = value
            self._timestamps[key] = time.time()

    def _evict_one(self):
        """淘汰一个条目（内部方法，调用前需持有锁）"""
        if not self._cache:
            return
        key, value = self._cache.popitem(last=False)
        self._timestamps.pop(key, None)
        if self._on_evict:
            try:
                self._on_evict(key, value)
            except Exception:
                pass

    def _remove_internal(self, key):
        """内部删除方法（调用前需持有锁）"""
        if key in self._cache:
            value = self._cache.pop(key)
            self._timestamps.pop(key, None)
            if self._on_evict:
                try:
                    self._on_evict(key, value)
                except Exception:
                    pass

    def delete(self, key):
        """删除缓存值"""
        with self._lock:
            self._remove_internal(key)

    def clear(self):
        """清空缓存"""
        with self._lock:
            # 触发所有淘汰回调
            if self._on_evict:
                for key, value in self._cache.items():
                    try:
                        self._on_evict(key, value)
                    except Exception:
                        pass
            self._cache.clear()
            self._timestamps.clear()

    def contains(self, key) -> bool:
        """检查是否包含指定键"""
        with self._lock:
            if key not in self._cache:
                return False
            # 检查过期
            if self._ttl is not None:
                access_time = self._timestamps.get(key, 0)
                if time.time() - access_time > self._ttl:
                    return False
            return True

    def size(self) -> int:
        """返回当前缓存大小"""
        with self._lock:
            return len(self._cache)

    def keys(self):
        """返回所有键"""
        with self._lock:
            return list(self._cache.keys())

    def values(self):
        """返回所有值"""
        with self._lock:
            return list(self._cache.values())

    def items(self):
        """返回所有键值对"""
        with self._lock:
            return list(self._cache.items())

    def __len__(self):
        return self.size()

    def __contains__(self, key):
        return self.contains(key)

    def __getitem__(self, key):
        result = self.get(key)
        if result is None and key not in self._cache:
            raise KeyError(key)
        return result

    def __setitem__(self, key, value):
        self.set(key, value)

    def __delitem__(self, key):
        self.delete(key)
