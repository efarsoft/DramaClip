"""
分析结果缓存服务
P0 核心：缓存 ASR、情绪分析等结果，避免重复计算

缓存策略：
1. 基于视频文件哈希（大小 + 修改时间 + 前1MB内容）
2. LRU 缓存，内存中保留最近 N 个结果
3. 磁盘持久化缓存，重启后可复用
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from loguru import logger
from collections import OrderedDict


@dataclass
class CacheEntry:
    """缓存条目"""
    video_hash: str
    video_path: str
    result_type: str  # "asr", "emotion", "visual", "rhythm"
    result_data: Dict[str, Any]
    created_at: float
    access_count: int = 0
    last_accessed: float = 0

    def to_dict(self) -> Dict:
        return {
            "video_hash": self.video_hash,
            "video_path": self.video_path,
            "result_type": self.result_type,
            "result_data": self.result_data,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CacheEntry":
        return cls(**data)


class AnalysisCache:
    """
    分析结果缓存

    提供内存缓存 + 磁盘持久化两层缓存
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_memory_entries: int = 50,
        max_disk_entries: int = 500,
        ttl_seconds: int = 7 * 24 * 3600,  # 7天
    ):
        """
        初始化缓存

        Args:
            cache_dir: 磁盘缓存目录
            max_memory_entries: 内存缓存最大条目数
            max_disk_entries: 磁盘缓存最大条目数
            ttl_seconds: 缓存过期时间（秒）
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".dramaclip" / "cache" / "analysis"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.max_memory_entries = max_memory_entries
        self.max_disk_entries = max_disk_entries
        self.ttl_seconds = ttl_seconds

        # 内存缓存：OrderedDict 实现 LRU
        self._memory_cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # 加载磁盘缓存索引
        self._index_file = self.cache_dir / "cache_index.json"
        self._disk_index: Dict[str, Dict] = {}
        self._load_index()

        logger.info(
            f"[Cache] 初始化: 内存={max_memory_entries}, "
            f"磁盘={max_disk_entries}, TTL={ttl_seconds}s"
        )

    def _load_index(self):
        """加载磁盘缓存索引"""
        if self._index_file.exists():
            try:
                self._disk_index = json.loads(self._index_file.read_text(encoding="utf-8"))
                logger.debug(f"[Cache] 加载了 {len(self._disk_index)} 个磁盘缓存条目")
            except Exception as e:
                logger.warning(f"[Cache] 加载索引失败: {e}")
                self._disk_index = {}

    def _save_index(self):
        """保存磁盘缓存索引"""
        try:
            self._index_file.write_text(
                json.dumps(self._disk_index, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[Cache] 保存索引失败: {e}")

    def get_video_hash(self, video_path: str) -> str:
        """
        计算视频文件哈希

        使用文件大小 + 修改时间 + 前1MB内容
        """
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        stat = path.stat()

        # 取前1MB内容
        hash_content = f"{stat.st_size}_{stat.st_mtime}".encode()
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024 * 1024)  # 1MB
                hash_content += chunk
        except Exception:
            pass

        return hashlib.sha256(hash_content).hexdigest()

    def get(
        self,
        video_path: str,
        result_type: str,
        video_hash: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取缓存结果

        Args:
            video_path: 视频文件路径
            result_type: 结果类型 ("asr", "emotion", etc.)
            video_hash: 可选的视频哈希（避免重复计算）

        Returns:
            缓存的结果，或 None
        """
        try:
            if video_hash is None:
                video_hash = self.get_video_hash(video_path)
        except FileNotFoundError:
            return None

        cache_key = f"{video_hash}_{result_type}"

        # 1. 先查内存缓存
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            # 更新访问统计
            entry.access_count += 1
            entry.last_accessed = time.time()
            # 移到末尾（LRU）
            self._memory_cache.move_to_end(cache_key)
            logger.debug(f"[Cache] 命中内存缓存: {cache_key}")
            return entry.result_data

        # 2. 查磁盘缓存
        if cache_key in self._disk_index:
            disk_entry = self._disk_index[cache_key]

            # 检查是否过期
            if time.time() - disk_entry["created_at"] > self.ttl_seconds:
                self._evict_disk_entry(cache_key)
                return None

            # 加载到内存
            disk_file = self.cache_dir / f"{cache_key}.json"
            if disk_file.exists():
                try:
                    data = json.loads(disk_file.read_text(encoding="utf-8"))
                    entry = CacheEntry.from_dict(data)

                    # 更新访问统计
                    entry.access_count += 1
                    entry.last_accessed = time.time()

                    # 加入内存缓存（可能需要淘汰）
                    self._add_to_memory_cache(cache_key, entry)

                    logger.debug(f"[Cache] 命中磁盘缓存: {cache_key}")
                    return entry.result_data
                except Exception as e:
                    logger.warning(f"[Cache] 加载磁盘缓存失败: {e}")

        return None

    def set(
        self,
        video_path: str,
        result_type: str,
        result_data: Dict[str, Any],
        video_hash: Optional[str] = None,
    ) -> bool:
        """
        保存结果到缓存

        Args:
            video_path: 视频文件路径
            result_type: 结果类型
            result_data: 要缓存的结果数据
            video_hash: 可选的视频哈希

        Returns:
            是否保存成功
        """
        try:
            if video_hash is None:
                video_hash = self.get_video_hash(video_path)
        except FileNotFoundError:
            return False

        cache_key = f"{video_hash}_{result_type}"
        now = time.time()

        entry = CacheEntry(
            video_hash=video_hash,
            video_path=video_path,
            result_type=result_type,
            result_data=result_data,
            created_at=now,
            access_count=1,
            last_accessed=now,
        )

        # 保存到磁盘
        disk_file = self.cache_dir / f"{cache_key}.json"
        try:
            disk_file.write_text(
                json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self._disk_index[cache_key] = entry.to_dict()
            self._save_index()
        except Exception as e:
            logger.warning(f"[Cache] 保存磁盘缓存失败: {e}")
            return False

        # 加入内存缓存
        self._add_to_memory_cache(cache_key, entry)

        logger.debug(f"[Cache] 保存缓存: {cache_key}")
        return True

    def _add_to_memory_cache(self, cache_key: str, entry: CacheEntry):
        """加入内存缓存，可能需要淘汰"""
        # 如果已存在，先删除
        if cache_key in self._memory_cache:
            del self._memory_cache[cache_key]

        # 如果超过最大数量，淘汰最旧的
        while len(self._memory_cache) >= self.max_memory_entries:
            oldest_key, _ = self._memory_cache.popitem(last=False)
            logger.debug(f"[Cache] 淘汰内存缓存: {oldest_key}")

        self._memory_cache[cache_key] = entry

    def _evict_disk_entry(self, cache_key: str):
        """淘汰磁盘缓存条目"""
        disk_file = self.cache_dir / f"{cache_key}.json"
        if disk_file.exists():
            try:
                disk_file.unlink()
            except Exception:
                pass

        if cache_key in self._disk_index:
            del self._disk_index[cache_key]
            self._save_index()

        logger.debug(f"[Cache] 淘汰磁盘缓存: {cache_key}")

    def clear_expired(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的条目数
        """
        now = time.time()
        expired_keys = []

        for cache_key, entry_data in self._disk_index.items():
            if now - entry_data["created_at"] > self.ttl_seconds:
                expired_keys.append(cache_key)

        for key in expired_keys:
            self._evict_disk_entry(key)

        logger.info(f"[Cache] 清理了 {len(expired_keys)} 个过期缓存")
        return len(expired_keys)

    def clear_all(self) -> int:
        """
        清空所有缓存

        Returns:
            清空的条目数
        """
        count = len(self._disk_index)

        # 清空内存
        self._memory_cache.clear()

        # 清空磁盘
        for cache_key in list(self._disk_index.keys()):
            self._evict_disk_entry(cache_key)

        logger.info(f"[Cache] 清空了所有缓存，共 {count} 条")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": len(self._disk_index),
            "max_memory": self.max_memory_entries,
            "max_disk": self.max_disk_entries,
            "ttl_seconds": self.ttl_seconds,
            "cache_dir": str(self.cache_dir),
        }


# 全局单例
_cache: Optional[AnalysisCache] = None


def get_analysis_cache() -> AnalysisCache:
    """获取分析缓存实例"""
    global _cache
    if _cache is None:
        _cache = AnalysisCache()
    return _cache


def clear_analysis_cache() -> int:
    """清空分析缓存"""
    return get_analysis_cache().clear_all()
