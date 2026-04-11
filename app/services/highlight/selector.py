"""
DramaClip - 高光片段筛选器

负责从打分后的片段中筛选出最优的高光集合：
1. Top-N 按比例筛选
2. 剧集均衡（每集至少N个）
3. 最小时长过滤
4. 总时长适配
"""

from typing import List, Optional
from loguru import logger
from collections import defaultdict

from app.models.schema import SceneSegment, HighlightConfig
from .scorer import ScoringResult


class HighlightSelector:
    """
    高光筛选器
    
    策略：
    1. 过滤掉过短/过长的碎片片段
    2. 按得分全局排序，选取 Top ratio%
    3. 剧集均衡：保证每集至少有 min_episodes_covered 个片段
    4. 适配目标输出时长（可选）
    """
    
    def __init__(self, config: Optional[HighlightConfig] = None):
        self.config = config or HighlightConfig()
    
    def select(self,
                scored_results: List[ScoringResult],
                target_duration: Optional[float] = None,
                progress_callback=None) -> List[SceneSegment]:
        """
        从打分结果中筛选高光片段
        
        Args:
            scored_results: 已打分的片段结果列表
            target_duration: 目标总时长(秒)，None则不限制
            progress_callback: 进度回调 function(progress_01, message)
            
        Returns:
            List[SceneSegment]: 筛选出的高光片段列表（按剧集+时间排序）
        """
        if not scored_results:
            logger.warning("没有可筛选的片段")
            return []
        
        cfg = self.config
        
        # ===== Step 1: 基础过滤（最小时长） =====#
        if progress_callback:
            progress_callback(0.1, "正在过滤碎片片段...")
        
        filtered = self._filter_by_duration(scored_results, cfg.min_segment_duration)
        
        if not filtered:
            logger.warning("过滤后没有剩余片段")
            return []
        
        # ===== Step 2: 全局 Top-N 筛选 =====#
        if progress_callback:
            progress_callback(0.3, "正在进行全局评分排序...")
        
        sorted_results = sorted(filtered, key=lambda r: r.total_score, reverse=True)
        top_n = max(1, int(len(sorted_results) * cfg.top_ratio))
        top_results = sorted_results[:top_n]
        
        # ===== Step 3: 剧集均衡 =====#
        if progress_callback:
            progress_callback(0.6, "正在执行剧集均衡...")
        
        balanced = self._balance_episodes(
            top_results,
            all_results=sorted_results,
            min_episodes_covered=cfg.min_episodes_covered,
            max_per_episode=cfg.max_segments_per_episode
        )
        
        # ===== Step 4: 目标时长适配 =====#
        if progress_callback:
            progress_callback(0.8, "正在适配输出时长...")
        
        if target_duration:
            balanced = self._fit_target_duration(balanced, target_duration)
        
        # ===== Step 5: 排序 + 标记 =====#
        if progress_callback:
            progress_callback(0.95, "正在整理最终结果...")
        
        final_segments = self._finalize_selection(balanced)
        
        if progress_callback:
            total_dur = sum(s.duration for s in final_segments)
            progress_callback(1.0, f"完成! 筛选出 {len(final_segments)} 个片段, 总时长 {total_dur:.1f}s")
        
        return final_segments
    
    def _filter_by_duration(self, 
                             results: List[ScoringResult], 
                             min_duration: float) -> List[ScoringResult]:
        """过滤过短片段"""
        filtered = [r for r in results if r.segment.duration >= min_duration]
        removed_count = len(results) - len(filtered)
        if removed_count > 0:
            logger.info(f"时长过滤: 移除 {removed_count} 个过短片段 (<{min_duration}s)")
        return filtered
    
    def _balance_episodes(self,
                          top_results: List[ScoringResult],
                          all_results: List[ScoringResult],
                          min_episodes_covered: int = 1,
                          max_per_episode: int = 5) -> List[ScoringResult]:
        """剧集均衡：两阶段确保每集覆盖率
        
        Phase 1: 保证每集至少有1个片段
        Phase 2: 补充不足 min_episodes_covered 的剧集
        """
        episode_groups: dict[int, List[ScoringResult]] = defaultdict(list)
        for r in top_results:
            ep = r.segment.episode_index
            if len(episode_groups[ep]) < max_per_episode:
                episode_groups[ep].append(r)
        
        selected = list(top_results)
        already_selected_ids = {r.segment.segment_id for r in selected}
        all_episodes = set(r.segment.episode_index for r in all_results)
        
        # ===== Phase 1: 保证每集至少1个片段 =====#
        covered_episodes = set(episode_groups.keys())
        missing_episodes = all_episodes - covered_episodes
        
        for ep in sorted(missing_episodes):
            candidates = [
                r for r in all_results 
                if r.segment.episode_index == ep 
                and r.segment.segment_id not in already_selected_ids
            ]
            if candidates:
                best = max(candidates, key=lambda r: r.total_score)
                selected.append(best)
                already_selected_ids.add(best.segment.segment_id)
                logger.info(f"剧集均衡 Phase1: 为 E{ep} 补充了片段 {best.segment.segment_id}")
        
        # ===== Phase 2: 补充到 min_episodes_covered =====#
        episode_counts = defaultdict(int)
        for r in selected:
            episode_counts[r.segment.episode_index] += 1
        
        for ep in all_episodes:
            count = episode_counts.get(ep, 0)
            if count < min_episodes_covered:
                needed = min_episodes_covered - count
                extras = [
                    r for r in all_results
                    if r.segment.episode_index == ep
                    and r.segment.segment_id not in already_selected_ids
                ]
                # 按分数排序取前 N 个
                extras_sorted = sorted(extras, key=lambda r: r.total_score, reverse=True)[:needed]
                for extra in extras_sorted:
                    selected.append(extra)
                    already_selected_ids.add(extra.segment.segment_id)
                    episode_counts[ep] += 1
                    logger.info(f"剧集均衡 Phase2: 为 E{ep} 补充到 {episode_counts[ep]} 个片段")
        
        return selected
    
    def _fit_target_duration(self,
                              results: List[ScoringResult],
                              target_duration: float) -> List[ScoringResult]:
        """适配目标输出时长"""
        sorted_results = sorted(results, key=lambda r: r.total_score, reverse=True)
        
        current_duration = 0.0
        selected = []
        min_acceptable = target_duration * 0.70
        max_acceptable = target_duration * 1.30
        
        for r in sorted_results:
            seg = r.segment
            if (current_duration + seg.duration > max_acceptable and 
                current_duration >= min_acceptable):
                break
            selected.append(r)
            current_duration += seg.duration
            if current_duration >= target_duration * 0.95:
                break
        
        return selected
    
    def _finalize_selection(self, results: List[ScoringResult]) -> List[SceneSegment]:
        """排序、设置rank和selected标记"""
        sorted_results = sorted(
            results,
            key=lambda r: (r.segment.episode_index, r.segment.start_time)
        )
        
        segments = []
        for rank, r in enumerate(sorted_results, 1):
            seg = r.segment
            seg.rank = rank
            seg.selected = True
            segments.append(seg)
        
        logger.info(
            f"最终筛选: {len(segments)} 片段 | "
            f"{len(set(s.episode_index for s in segments))} 集 | "
            f"总时长 {sum(s.duration for s in segments):.1f}s"
        )
        
        return segments
    
    def get_selection_stats(self,
                            original_count: int,
                            selected: List[SceneSegment]) -> dict:
        """获取筛选统计信息"""
        episodes_represented = set(s.episode_index for s in selected)
        scores = [s.total_score or 0 for s in selected]
        
        return {
            "original_count": original_count,
            "selected_count": len(selected),
            "select_ratio": round(len(selected) / max(1, original_count), 3),
            "episodes_covered": len(episodes_represented),
            "total_duration": round(sum(s.duration for s in selected), 1),
            "avg_score": round(sum(scores) / max(1, len(scores)), 3),
            "max_score": round(max(scores), 3) if scores else 0,
            "min_score": round(min(scores), 3) if scores else 0,
        }
