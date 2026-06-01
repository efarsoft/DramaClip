"""
Narration 结果缓存服务

用于缓存 LLM 生成的解说脚本，避免对相同片段集合 + 相同风格重复调用 LLM。

缓存 Key 维度：
- segments 指纹（基于 start/end + reason 的哈希）
- mix_mode (overlay / replace)
- drama_name / project 相关标识
- prompt 版本（未来可扩展）

存储方式：磁盘 JSON（简单可靠，类似 analyze/cache.py）
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class NarrationCacheEntry:
    """Narration 缓存条目"""
    cache_key: str
    segments_fingerprint: str
    mix_mode: str
    drama_name: str
    script_data: Dict[str, Any]          # LLM 返回的 {"items": [...]}
    created_at: float
    access_count: int = 0


class NarrationCache:
    """Narration 脚本结果缓存管理器"""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / ".dramaclip" / "cache" / "narration"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, NarrationCacheEntry] = {}

    def _compute_segments_fingerprint(self, segments: List[Dict[str, Any]]) -> str:
        """为 segments 列表生成稳定指纹"""
        if not segments:
            return "empty"

        # 使用 start/end + reason 作为主要特征
        key_parts = []
        for seg in segments:
            start = seg.get("start_time") or seg.get("start") or 0.0
            end = seg.get("end_time") or seg.get("end") or 0.0
            reason = seg.get("reason") or seg.get("scene_description") or ""
            key_parts.append(f"{round(start, 2)}-{round(end, 2)}:{reason[:50]}")

        content = "|".join(key_parts)
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

    def _make_cache_key(self, segments: List[Dict], mix_mode: str, drama_name: str) -> str:
        fingerprint = self._compute_segments_fingerprint(segments)
        raw = f"{fingerprint}:{mix_mode}:{drama_name or 'default'}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, segments: List[Dict], mix_mode: str, drama_name: str = "") -> Optional[Dict]:
        """尝试获取缓存的解说脚本"""
        cache_key = self._make_cache_key(segments, mix_mode, drama_name)
        cache_file = self.cache_dir / f"{cache_key}.json"

        # 先查内存
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            entry.access_count += 1
            logger.info(f"[NarrationCache] Memory hit for key {cache_key[:8]}")
            return entry.script_data

        # 查磁盘
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                entry = NarrationCacheEntry(**data)
                entry.access_count += 1
                self._memory_cache[cache_key] = entry

                # 更新磁盘访问计数
                cache_file.write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2), encoding="utf-8")

                logger.info(f"[NarrationCache] Disk hit for key {cache_key[:8]} (mix_mode={mix_mode})")
                return entry.script_data
            except Exception as e:
                logger.warning(f"[NarrationCache] Failed to load cache {cache_file}: {e}")

        return None

    def set(self, segments: List[Dict], mix_mode: str, drama_name: str, script_data: Dict):
        """保存生成的解说脚本到缓存"""
        if not script_data or "items" not in script_data:
            return

        cache_key = self._make_cache_key(segments, mix_mode, drama_name)
        cache_file = self.cache_dir / f"{cache_key}.json"

        entry = NarrationCacheEntry(
            cache_key=cache_key,
            segments_fingerprint=self._compute_segments_fingerprint(segments),
            mix_mode=mix_mode,
            drama_name=drama_name or "default",
            script_data=script_data,
            created_at=time.time(),
            access_count=1
        )

        try:
            cache_file.write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2), encoding="utf-8")
            self._memory_cache[cache_key] = entry
            logger.info(f"[NarrationCache] Cached narration script for {len(segments)} segments (key={cache_key[:8]})")
        except Exception as e:
            logger.error(f"[NarrationCache] Failed to write cache: {e}")

    def clear(self):
        """清空缓存（用于测试或强制刷新）"""
        self._memory_cache.clear()
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass
        logger.info("[NarrationCache] Cache cleared")

    def invalidate_for_project(self, project_id: str):
        """
        当项目重新分析后调用，失效所有与该项目相关的 narration 缓存。
        简单实现：直接清空整个 narration 缓存（生产环境可做更细粒度基于 project_id 的清理）。
        """
        # 当前实现为简单粗暴清空（因为缓存 key 里包含 drama_name/project_name）
        self.clear()
        logger.info(f"[NarrationCache] 已因项目 {project_id} 重新分析而清空 narration 缓存")


# 全局单例
_narration_cache: Optional[NarrationCache] = None


def get_narration_cache() -> NarrationCache:
    global _narration_cache
    if _narration_cache is None:
        _narration_cache = NarrationCache()
    return _narration_cache
