"""
高光打分逻辑
从 manager.py 的 _run_highlight_detection 方法中提取出来，
实现多维度评分：情绪、视觉、节奏、说话人。
"""

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .types import ASRResultUnion
from .emotion_service import EmotionAnalysis
from .visual_service import VisualService, VisualAnalysis
from .rhythm_service import RhythmService, RhythmAnalysis
from .speaker_diarization_service import DiarizationResult


def _safe_float(val, default: float = 0.5) -> float:
    """辅助浮点安全转换"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def compute_highlight_scores(
    asr_result: ASRResultUnion,
    emotion_result: Optional[EmotionAnalysis],
    visual_result: Optional[VisualAnalysis],
    rhythm_result: Optional[RhythmAnalysis],
    diarization_result: Optional[DiarizationResult],
    visual_service: VisualService,
    rhythm_service: RhythmService,
    video_path: str,
) -> tuple:
    """
    计算每个字幕片段的多维度高光评分。

    Returns:
        (scored_segments, video_paths, start_times, end_times, subtitle_texts)
    """
    scored_segments: List[Dict] = []
    video_paths: List[str] = []
    start_times: List[float] = []
    end_times: List[float] = []
    subtitle_texts: List[Optional[str]] = []

    # 计算主导说话人（用于 speaker-aware 高光加分）
    dominant_speaker: Optional[str] = None
    if diarization_result and diarization_result.speakers:
        dominant_speaker = max(
            diarization_result.speakers,
            key=lambda s: s.total_duration,
        ).speaker_id if diarization_result.speakers else None

    for i, seg in enumerate(asr_result.segments):
        # ---------- 情绪分数 ----------
        emotion_score = 0.5
        if emotion_result and i < len(emotion_result.emotion_curve):
            ep = emotion_result.emotion_curve[i]
            intensity = ep.intensity if (ep and ep.intensity is not None) else 0.5
            confidence = ep.confidence if (ep and ep.confidence is not None) else 1.0
            try:
                emotion_score = float(intensity) * float(confidence)
            except (ValueError, TypeError):
                emotion_score = 0.5

        # ---------- 视觉分数 ----------
        visual_score = 0.5
        if visual_result:
            frame_data = visual_service.get_frame_score_at_time(
                visual_result, seg.start,
            )
            if frame_data:
                visual_score = visual_service.calculate_visual_score(
                    brightness=_safe_float(frame_data.get("brightness"), 0.5),
                    contrast=_safe_float(frame_data.get("contrast"), 0.5),
                    motion=_safe_float(frame_data.get("motion_score"), 0.0),
                    face_score=_safe_float(frame_data.get("face_score"), 0.0),
                    sharpness=_safe_float(frame_data.get("sharpness"), 0.5),
                )
            else:
                visual_score = 0.5

        # ---------- 节奏分数 ----------
        rhythm_score = 0.5
        if rhythm_result:
            point_data = rhythm_service.get_rhythm_score_at_time(
                rhythm_result, seg.start,
            )
            if point_data:
                rhythm_score = rhythm_service.calculate_rhythm_score(
                    energy=_safe_float(point_data.get("energy"), 0.5),
                    is_beat=bool(point_data.get("is_beat", False)),
                    is_silence=bool(point_data.get("is_silence", False)),
                    bpm_variance=_safe_float(rhythm_result.bpm_variance, 0.0),
                )
            else:
                rhythm_score = 0.5

        # ---------- 说话人分数（P5: speaker-aware） ----------
        speaker_score = 0.5
        seg_speaker = getattr(seg, "speaker", None)
        if diarization_result and seg_speaker:
            # 主导角色加成
            if dominant_speaker and seg_speaker == dominant_speaker:
                speaker_score = min(1.0, speaker_score + 0.18)
            # 说话人变化点轻微加分（对话高光）
            prev_speaker = (
                getattr(asr_result.segments[i - 1], "speaker", None) if i > 0 else None
            )
            next_speaker = (
                getattr(asr_result.segments[i + 1], "speaker", None)
                if i + 1 < len(asr_result.segments)
                else None
            )
            if (prev_speaker and prev_speaker != seg_speaker) or (
                next_speaker and next_speaker != seg_speaker
            ):
                speaker_score = min(1.0, speaker_score + 0.07)

        # ---------- 原声保护重要性 ----------
        subtitle_len = len(seg.text or "")
        dialogue_importance = min(1.0, (subtitle_len / 80.0) * 0.6 + emotion_score * 0.4)

        scored_segments.append({
            "audio_score": 0.5,
            "emotion_score": emotion_score,
            "visual_score": visual_score,
            "rhythm_score": rhythm_score,
            "speaker_score": speaker_score,
            "dialogue_importance": dialogue_importance,
            "speaker": seg_speaker,
        })
        video_paths.append(video_path)
        start_times.append(seg.start)
        end_times.append(seg.end)
        subtitle_texts.append(seg.text)

    return scored_segments, video_paths, start_times, end_times, subtitle_texts


def run_highlight_detection(
    asr_result: ASRResultUnion,
    emotion_result: Optional[EmotionAnalysis],
    visual_result: Optional[VisualAnalysis],
    rhythm_result: Optional[RhythmAnalysis],
    diarization_result: Optional[DiarizationResult],
    visual_service: VisualService,
    rhythm_service: RhythmService,
    video_path: str,
) -> List[Dict]:
    """
    运行完整的高光识别流程：打分 + 选择。

    Returns:
        高光片段列表（字典格式）
    """
    from app.services.highlight.selector import HighlightSelector

    scored_segments, video_paths, start_times, end_times, subtitle_texts = (
        compute_highlight_scores(
            asr_result,
            emotion_result,
            visual_result,
            rhythm_result,
            diarization_result,
            visual_service,
            rhythm_service,
            video_path,
        )
    )

    selector = HighlightSelector()
    selected = selector.select_from_scores(
        scored_segments=scored_segments,
        video_paths=video_paths,
        start_times=start_times,
        end_times=end_times,
        subtitle_texts=subtitle_texts,
    )

    result = [h.to_dict() for h in selected]
    logger.info(f"Highlight detection completed: {len(result)} highlights")
    return result
