"""
ASR 语音识别服务（简化版）
"""

from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class ASRSegment:
    """ASR 识别片段"""
    id: str
    text: str
    start: float
    end: float
    speaker: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
        }


@dataclass
class ASRResult:
    """ASR 识别结果"""
    segments: List[ASRSegment] = field(default_factory=list)
    language: str = "zh"
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "language": self.language,
            "duration": self.duration,
        }


# 简化版 ASR 服务 - 返回模拟数据


def whisper_asr(
    audio_path: str,
    model: str = "base",
    language: str = "zh",
    progress_callback=None,
) -> List[Dict]:
    """
    语音识别函数（简化版）

    Returns:
        [{"text": "台词", "start": 0.0, "end": 5.0, "speaker": "角色1"}]
    """
    results = [
        {"id": "1", "text": "这是第一段对话内容。", "start": 0.0, "end": 3.5, "speaker": "角色1"},
        {"id": "2", "text": "这是第二段，包含更多对话。", "start": 4.0, "end": 8.2, "speaker": "角色2"},
        {"id": "3", "text": "第三段台词用于演示情绪分析。", "start": 9.5, "end": 15.0, "speaker": "角色1"},
    ]
    return results


class ASRService:
    """ASR 服务类"""

    def recognize(self, audio_path: str, language: str = "zh", progress_callback=None) -> ASRResult:
        """执行语音识别，返回 ASRResult"""
        raw_results = whisper_asr(
            audio_path,
            language=language,
            progress_callback=progress_callback,
        )
        segments = [
            ASRSegment(
                id=r["id"],
                text=r["text"],
                start=float(r["start"]),
                end=float(r["end"]),
                speaker=r.get("speaker", ""),
            )
            for r in raw_results
        ]
        duration = max((s.end for s in segments), default=0.0)
        return ASRResult(segments=segments, language=language, duration=duration)

    def save_result(self, result, output_path):
        pass
