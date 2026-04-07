"""
DramaClip - 镜头节奏评分器

分析镜头片段的节奏特征：
- 片段时长（2~5秒为最佳高光长度）
- 镜头切换频率
- 在剧集中的位置（开头/中段/结尾）
"""

from typing import Tuple
from loguru import logger


class RhythmScorer:
    """
    镜头节奏评分器
    
    评估片段的"剪辑友好度"——是否适合作为高光片段。
    
    分析维度：
    1. 时长适配度 (40%) — 2~5秒为最佳区间
    2. 位置因子 (30%) — 剧集中后段更可能是高潮位置
    3. 节奏变化 (20%) — 与前后片段的对比
    4. 完整度 (10%) — 是否被截断
    """
    
    # 最佳时长范围（秒）
    OPTIMAL_DURATION_MIN = 2.0
    OPTIMAL_DURATION_MAX = 6.0
    IDEAL_DURATION = 4.0  # 最理想时长
    MIN_MARGIN_SECONDS = 0.5  # 边界最小留白时间
    
    def __init__(self, 
                 optimal_min: float = None,
                 optimal_max: float = None):
        self.optimal_min = optimal_min or self.OPTIMAL_DURATION_MIN
        self.optimal_max = optimal_max or self.OPTIMAL_DURATION_MAX
    
    def score(self,
              duration: float,
              start_time: float,
              episode_duration: float,
              episode_index: int = 1,
              total_episodes: int = 1) -> Tuple[float, dict]:
        """
        对镜头片段进行节奏评分
        
        Args:
            duration: 片段时长(秒)
            start_time: 片段起始时间(秒)
            episode_duration: 所在剧集总时长(秒)
            episode_index: 剧集序号
            total_episodes: 总集数
            
        Returns:
            tuple: (得分0~1, 详细分析结果dict)
        """
        
        # 入口守卫：无效时长
        if duration <= 0:
            return 0.0, {"error": "invalid_duration", "duration": duration}
        if episode_duration <= 0:
            # 无法做位置和边界判断，给一个基础分
            return 0.4 * self._score_duration(duration), {
                "error": "invalid_episode_duration",
                "duration_score": self._score_duration(duration),
            }
        
        # ===== 1. 时长适配度 (40%) =====#
        duration_score = self._score_duration(duration)
        
        # ===== 2. 位置因子 (30%) =====#
        position_score = self._score_position(start_time, episode_duration)
        
        # ===== 3. 节奏变化 (20%) =====#
        # 短片段密集出现区域 = 节奏快 = 可能是打斗/冲突场景
        rhythm_score = self._score_rhythm(duration, start_time)
        
        # ===== 4. 完整度/边界安全 (10%) =====#
        boundary_score = self._score_boundary(start_time, duration, episode_duration)
        
        # 综合得分
        total_score = (
            0.40 * duration_score +
            0.30 * position_score +
            0.20 * rhythm_score +
            0.10 * boundary_score
        )
        
        total_score = max(0.0, min(1.0, total_score))
        
        details = {
            "duration_score": round(duration_score, 4),
            "position_score": round(position_score, 4),
            "rhythm_score": round(rhythm_score, 4),
            "boundary_score": round(boundary_score, 4),
            "total_score": round(total_score, 4),
            "duration": round(duration, 2),
            "start_time": round(start_time, 2),
            "episode_position_ratio": round(start_time / max(1, episode_duration), 4),
            "duration_rating": self._rate_duration(duration),
            "is_optimal_length": self.optimal_min <= duration <= self.optimal_max,
        }
        
        return total_score, details
    
    def _score_duration(self, duration: float) -> float:
        """时长适配度评分"""
        if duration < 0.5:
            # 太短，几乎不可用
            return 0.05
        
        elif duration < self.optimal_min:
            # 偏短，线性递减
            ratio = duration / self.optimal_min
            return 0.3 + 0.5 * ratio
        
        elif duration <= self.optimal_max:
            # 最佳区间内，接近理想值得分更高
            distance_from_ideal = abs(duration - self.IDEAL_DURATION)
            max_distance = max(
                self.IDEAL_DURATION - self.optimal_min,
                self.optimal_max - self.IDEAL_DURATION
            )
            score = 1.0 - 0.3 * (distance_from_ideal / max(1, max_distance))
            return max(0.7, score)
        
        else:
            # 偏长，逐渐降低
            excess = duration - self.optimal_max
            return max(0.3, 0.8 - excess / 15.0)  # 每15秒降0.15分
    
    def _score_position(self, start_time: float, episode_duration: float) -> float:
        """位置因子评分
        
        经验规律：短剧的高潮通常分布如下：
        - 开头(0~15%): 引子、悬念铺设 → 中等偏上
        - 前段(15~35%): 冲突铺垫 → 中等
        - 中段(35~65%): 冲突升级 → 较好
        - 后段(65~85%): 高潮爆发 → 最好
        - 结尾(85~100%): 反转/收尾 → 中等偏上
        """
        if episode_duration <= 0:
            return 0.5
        
        ratio = start_time / episode_duration
        
        if ratio < 0.10:
            # 开场（可能有黄金开场）
            return 0.75
        elif ratio < 0.25:
            # 前段铺垫
            return 0.55 + 0.2 * (ratio / 0.25)
        elif ratio < 0.50:
            # 中前段
            return 0.70 + 0.15 * ((ratio - 0.25) / 0.25)
        elif ratio < 0.75:
            # 中后段到高潮（最可能的位置）
            return 0.85 + 0.12 * ((ratio - 0.50) / 0.25)
        elif ratio < 0.90:
            # 高潮延续
            return 0.90 + 0.05 * ((ratio - 0.75) / 0.15)
        else:
            # 结尾反转区
            return 0.80
    
    def _score_rhythm(self, duration: float, start_time: float) -> float:
        """节奏变化评分"""
        
        # 短片段（<3秒）= 快节奏 = 可能有动作/对话交锋
        if duration < 2.0:
            short_intensity = 0.9
        elif duration < 4.0:
            short_intensity = 0.7
        elif duration < 6.0:
            short_intensity = 0.5
        else:
            short_intensity = 0.3
        
        # 整数秒附近的片段可能对应自然切镜点
        is_near_cut_point = (start_time % 1.0) < 0.3 or (start_time % 1.0) > 0.7
        cut_point_bonus = 0.15 if is_near_cut_point else 0.0
        
        score = 0.8 * short_intensity + 0.2 * (1.0 - cut_point_bonus)
        return score
    
    def _score_boundary(self, start_time: float, 
                        duration: float, 
                        episode_duration: float) -> float:
        """边界完整度评分（避免选择太靠近开头/结尾的片段）"""
        if episode_duration <= 0:
            return 0.5
        
        end_time = start_time + duration
        
        # 开头留白
        head_margin = start_time
        head_ok = head_margin >= self.MIN_MARGIN_SECONDS
        
        # 结尾留白
        tail_margin = episode_duration - (start_time + duration)
        tail_ok = tail_margin >= self.MIN_MARGIN_SECONDS
        
        if head_ok and tail_ok:
            return 1.0
        elif head_ok or tail_ok:
            return 0.6
        else:
            return 0.3
    
    def _rate_duration(self, duration: float) -> str:
        """返回时长评级文字"""
        if duration < 1.0:
            return "过短"
        elif duration < self.optimal_min:
            return "偏短"
        elif duration <= self.optimal_max:
            return "理想"
        elif duration <= 10.0:
            return "偏长"
        else:
            return "过长"
