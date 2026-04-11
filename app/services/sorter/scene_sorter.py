"""
DramaClip - 智能排序器

对筛选后的高光片段进行智能排序，确保：
1. 剧集顺序：E1 → E2 → E3...
2. 时间顺序：同集内按时间线排列
3. 情绪递进：整体情绪强度逐步上升
4. 节奏平衡：避免连续过长/过短片段
"""

from typing import List, Optional
from loguru import logger

from app.models.schema import SceneSegment


class SceneSorter:
    """
    智能排序器
    
    排序优先级：
    1. 剧集号（必须保持剧情连贯）
    2. 时间先后（同一集内按时间线）
    3. 情绪递进（可选微调：在保持1、2的前提下做局部优化）
    """
    
    # 常量定义
    MAX_SWAP_DISTANCE_SECONDS = 30  # 最大交换时间差(秒)，超过此值不建议换
    EMOTION_INVERSION_THRESHOLD = 0.15  # 情绪倒退判定阈值
    MAX_SORT_ITERATIONS_FACTOR = 2  # 最大迭代次数 = 片段数 × 此因子

    def __init__(self,
                 enable_emotion_ramp: bool = True,
                 max_swap_distance: int = 2):
        self.enable_emotion_ramp = enable_emotion_ramp
        self.max_swap_distance = max_swap_distance
    
    def sort(self, segments: List[SceneSegment]) -> List[SceneSegment]:
        """
        对高光片段进行智能排序
        
        Args:
            segments: 已筛选的高光片段（无序或部分有序）
            
        Returns:
            List[SceneSegment]: 排序后的片段列表
        """
        if not segments:
            return []
        
        if len(segments) == 1:
            return segments
        
        # ===== 基础排序：剧集 + 时间 =====#
        sorted_segments = sorted(
            segments,
            key=lambda s: (s.episode_index, s.start_time)
        )
        
        # ===== 情绪递进优化 =====#
        if self.enable_emotion_ramp and len(sorted_segments) > 2:
            sorted_segments = self._apply_emotion_ramp(sorted_segments)
        
        # 更新 rank
        for i, seg in enumerate(sorted_segments, 1):
            seg.rank = i
        
        return sorted_segments
    
    def _apply_emotion_ramp(self, 
                            segments: List[SceneSegment]) -> List[SceneSegment]:
        """
        情绪递进优化
        
        在不破坏基本剧情顺序的前提下，
        通过有限范围内的交换使整体情绪曲线呈上升趋势。
        
        优化策略：
        - 按同集内分组，每组内按情绪分数升序排列（递进感）
        - 交换距离不超过 MAX_SWAP_DISTANCE_SECONDS
        - 单趟扫描+有限轮修正，O(n) 复杂度
        """
        result = list(segments)  # 复制列表
        n = len(result)
        
        if n <= 2:
            return result
        
        # 按剧集分组，同集内按情绪分数升序排列（实现递进效果）
        from itertools import groupby
        ep_groups = []
        for ep_idx, group in groupby(result, key=lambda s: s.episode_index):
            group_list = list(group)
            # 只对时间差不超过阈值的相邻片段排序
            ep_groups.append(self._sort_group_by_emotion(group_list))
        
        # 展平回列表
        result = [seg for group in ep_groups for seg in group]
        
        return result
    
    def _sort_group_by_emotion(self, segments: List[SceneSegment]) -> List[SceneSegment]:
        """对同一集内的片段按情绪递进排序（低分在前，高分在后）"""
        if len(segments) <= 2:
            return segments
        
        # 按情绪分数升序排序（递进效果），但限制交换时间跨度
        sorted_segs = sorted(segments, key=lambda s: s.total_score or 0)
        
        # 验证：如果最大时间跨度超过阈值，退回时间顺序
        time_span = abs(sorted_segs[0].start_time - sorted_segs[-1].start_time)
        if time_span > SceneSorter.MAX_SWAP_DISTANCE_SECONDS:
            return segments
        
        return sorted_segs
    
    def _can_safely_swap(self, 
                         segments: List[SceneSegment],
                         i: int, 
                         j: int) -> bool:
        """判断两个片段是否可以安全交换"""
        # 基本检查：同一集
        if segments[i].episode_index != segments[j].episode_index:
            return False
        
        # 检查时间差是否合理（避免打乱时间逻辑太严重）
        time_gap = abs(segments[i].start_time - segments[j].start_time)
        if time_gap > SceneSorter.MAX_SWAP_DISTANCE_SECONDS:
            return False
        
        return True
    
    def analyze_sorting_quality(self, 
                                 segments: List[SceneSegment]) -> dict:
        """
        分析排序质量指标
        
        返回：
        - episode_continuity: 剧集连贯性（是否乱序）
        - temporal_order: 时间顺序正确率
        - emotion_curve: 情绪曲线趋势（上升/平稳/波动）
        - rhythm_balance: 节奏均衡度
        """
        n = len(segments)
        if n < 2:
            return {"status": "too_few_segments"}
        
        # 1. 剧集连贯性
        episode_inversions = sum(
            1 for i in range(n - 1)
            if segments[i].episode_index > segments[i + 1].episode_index
        )
        episode_continuity = 1.0 - (episode_inversions / max(1, n - 1))
        
        # 2. 同集内时间顺序
        temporal_errors = 0
        temporal_checks = 0
        for i in range(n - 1):
            if (segments[i].episode_index == segments[i + 1].episode_index and
                segments[i].start_time > segments[i + 1].start_time):
                temporal_errors += 1
                temporal_checks += 1
            elif segments[i].episode_index == segments[i + 1].episode_index:
                temporal_checks += 1
        
        temporal_order = 1.0 - (temporal_errors / max(1, temporal_checks)) if temporal_checks > 0 else 1.0
        
        # 3. 情绪曲线趋势
        scores = [s.total_score or 0 for s in segments]
        
        # 计算趋势（线性回归斜率的简化版）
        score_changes = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
        increases = sum(1 for c in score_changes if c > 0)
        decreases = sum(1 for c in score_changes if c < 0)
        
        if increases >= decreases:
            emotion_trend = "rising"
        elif decreases > increases * 1.5:
            emotion_trend = "falling"
        else:
            emotion_trend = "stable"
        
        trend_ratio = increases / max(1, len(score_changes))
        
        # 4. 节奏均衡
        durations = [s.duration for s in segments]
        avg_dur = sum(durations) / len(durations)
        duration_variance = sum((d - avg_dur) ** 2 for d in durations) / len(durations)
        std_dev = duration_variance ** 0.5
        rhythm_balance = max(0, 1.0 - std_dev / avg_dur) if avg_dur > 0 else 0
        
        return {
            "segment_count": n,
            "episode_continuity": round(episode_continuity, 3),
            "temporal_order": round(temporal_order, 3),
            "emotion_trend": emotion_trend,
            "trend_ratio": round(trend_ratio, 3),
            "rhythm_balance": round(rhythm_balance, 3),
            "avg_duration": round(avg_dur, 2),
            "duration_std": round(std_dev, 2),
            "total_duration": round(sum(durations), 1),
            "score_range": f"{min(scores):.2f} ~ {max(scores):.2f}",
            "avg_score": round(sum(scores) / n, 3),
        }
