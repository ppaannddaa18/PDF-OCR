"""LRU缓存实现，用于管理内存中的图像和结果缓存"""
from collections import OrderedDict


class LRUCache:
    """简单的LRU缓存实现"""

    def __init__(self, max_size: int = 20):
        self._cache = OrderedDict()
        self._max_size = max_size

    def get(self, key, default=None):
        """获取缓存值，如果存在则更新访问顺序"""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return default

    def set(self, key, value):
        """设置缓存值，如果超过容量则淘汰最久未使用的"""
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def delete(self, key):
        """删除缓存值"""
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        """清空缓存"""
        self._cache.clear()

    def contains(self, key) -> bool:
        """检查是否包含指定键"""
        return key in self._cache

    def size(self) -> int:
        """返回当前缓存大小"""
        return len(self._cache)

    def keys(self):
        """返回所有键"""
        return list(self._cache.keys())

    def __len__(self):
        return len(self._cache)

    def __contains__(self, key):
        return key in self._cache

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)