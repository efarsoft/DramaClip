"""
DramaClip - 多维度高光打分引擎

统一协调四个子评分器，输出每个镜头片段的综合精彩度得分。
核心公式: score = 0.4×音频爆点 + 0.3×台词情绪 + 0.2×画面特征 + 0.1×镜头节奏
"""

from typing import List, Optional, Dict, Tuple
from loguru import logger
from dataclasses import dataclass

from app.models.schema import SceneSegment, HighlightScoreWeights, HighlightConfig


@dataclass
class ScoringResult:
    """单个片段的完整评分结果"""
    segment: SceneSegment
    audio_score: float
    emotion_score: float
    visual_score: float
    rhythm_score: float
    total_score: float
    details: Dict[str, dict]


class HighlightScorer:
    """
    DramaClip 核心引擎 — 多维度高光打分
    
    使用流程：
    1. 实例化 scorer = HighlightScorer(config)
    2. 对所有镜头调用 scorer.score_segments(segments)
    3. 获取带分的 segments 列表
    4. 调用 selector 进行筛选
    """
    
    def __init__(self, config: Optional[HighlightConfig] = None):
        self.config = config or HighlightConfig()
        self.weights = config.weights if config else HighlightScoreWeights()
        
        # 延迟导入子评分器（避免启动时加载重依赖）
        from .audio_scorer import AudioScorer
        from .emotion_scorer import EmotionScorer  
        from .visual_scorer import VisualScorer
        from .rhythm_scorer import RhythmScorer
        
        self.audio_scorer = AudioScorer()
        self.emotion_scorer = EmotionScorer()
        self.visual_scorer = VisualScorer()
        self.rhythm_scorer = RhythmScorer()
    
    def score_segment(self, segment: SceneSegment) -> ScoringResult:
        """
        对单个片段进行多维度打分
        
        Args:
            segment: 镜头片段对象
            
        Returns:
            ScoringResult: 完整的评分结果
        """
        details = {}
        
        # ===== 1. 音频爆点得分 (权重由配置决定) =====#
        audio_score = 0.0
        if segment.audio_path:
            try:
                audio_score, audio_details = self.audio_scorer.score(segment.audio_path)
                details['audio'] = audio_details
            except Exception as e:
                logger.warning(f"音频评分失败 (segment {segment.segment_id}): {e}")
                audio_score = 0.3  # 默认中等分
        else:
            # 无音频文件时给一个基于时长的默认分
            audio_score = self._default_audio_score(segment.duration)
            details['audio'] = {"method": "default"}
        
        # ===== 2. 台词情绪得分 =====#
        emotion_score = 0.0
        if segment.subtitle_text:
            try:
                emotion_score, emotion_details = self.emotion_scorer.score(segment.subtitle_text)
                details['emotion'] = emotion_details
            except Exception as e:
                logger.warning(f"情绪评分失败 (segment {segment.segment_id}): {e}")
                emotion_score = 0.2
        else:
            # 无字幕文本
            emotion_score = 0.1
            details['emotion'] = {"method": "no_text"}
        
        # ===== 3. 画面特征得分 =====#
        visual_score = 0.0
        if segment.video_path:
            try:
                visual_score, visual_details = self.visual_scorer.score(
                    segment.video_path, 
                    duration=segment.duration
                )
                details['visual'] = visual_details
                
                # 同步画面分析结果到 segment
                if 'face_center' in visual_details and visual_details.get('face_center'):
                    fc = visual_details['face_center']
                    segment.face_center_x = fc[0] if isinstance(fc, (tuple, list)) else None
                    segment.face_center_y = fc[1] if isinstance(fc, (tuple, list)) else None
                segment.has_face = visual_details.get('has_face_ratio', 0) > 0.3
                segment.is_closeup = visual_details.get('closeup_ratio', 0) > 0.3
                
            except Exception as e:
                logger.warning(f"画面评分失败 (segment {segment.segment_id}): {e}")
                visual_score = 0.3
        else:
            visual_score = 0.2
            details['visual'] = {"method": "no_video"}
        
        # ===== 4. 镜头节奏得分 =====#
        try:
            rhythm_score, rhythm_details = self.rhythm_scorer.score(
                duration=segment.duration,
                start_time=segment.start_time,
                episode_duration=getattr(segment, '_episode_duration', segment.end_time),
                episode_index=segment.episode_index,
            )
            details['rhythm'] = rhythm_details
        except Exception as e:
            logger.warning(f"节奏评分失败 (segment {segment.segment_id}): {e}")
            rhythm_score = self._default_rhythm_score(segment.duration)
            details['rhythm'] = {"method": "default"}
        
        # ===== 综合加权得分 =====#
        w = self.weights
        total_score = (
            w.audio_weight * audio_score +
            w.emotion_weight * emotion_score +
            w.visual_weight * visual_score +
            w.rhythm_weight * rhythm_score
        )
        total_score = max(0.0, min(1.0, total_score))
        
        # 更新 segment 的分数字段
        segment.audio_score = round(audio_score, 4)
        segment.emotion_score = round(emotion_score, 4)
        segment.visual_score = round(visual_score, 4)
        segment.rhythm_score = round(rhythm_score, 4)
        segment.total_score = round(total_score, 4)
        
        return ScoringResult(
            segment=segment,
            audio_score=audio_score,
            emotion_score=emotion_score,
            visual_score=visual_score,
            rhythm_score=rhythm_score,
            total_score=total_score,
            details=details,
        )
    
    def score_segments(self, 
                       segments: List[SceneSegment],
                       progress_callback=None) -> List[ScoringResult]:
        """
        批量对所有片段进行打分
        
        Args:
            segments: 所有镜头片段列表
            progress_callback: 进度回调 function(progress_01, message)
            
        Returns:
            List[ScoringResult]: 按原顺序排列的评分结果
        """
        results = []
        total = len(segments)
        
        for i, seg in enumerate(segments):
            if progress_callback:
                progress_callback((i + 1) / total, f"正在分析片段 {i+1}/{total}...")
            
            result = self.score_segment(seg)
            results.append(result)
            
            logger.debug(
                f"Segment {seg.segment_id} (E{seg.episode_index} "
                f"{seg.start_time:.1f}s-{seg.end_time:.1f}s): "
                f"score={result.total_score:.3f}"
            )
        
        if progress_callback:
            progress_callback(1.0, f"完成! 共分析 {total} 个片段")
        
        return results
    
    def _default_audio_score(self, duration: float) -> float:
        """无音频时的默认评分（基于时长推测）"""
        # 短片段更可能是高能片段
        if 2 <= duration <= 5:
            return 0.45
        elif 1 <= duration <= 8:
            return 0.30
        return 0.15
    
    def _default_rhythm_score(self, duration: float) -> float:
        """节奏评分降级方案"""
        r, _ = self.rhythm_scorer.score(
            duration=duration,
            start_time=0,
            episode_duration=max(duration * 3, 10)
        )
        return r
