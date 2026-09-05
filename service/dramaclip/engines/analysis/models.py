"""分析引擎数据模型（跨进程边界，字段对齐 protocol/schemas/analysis.json）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AsrSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str | None = None
    emotion: str | None = None


class SceneInfo(BaseModel):
    start: float
    end: float


class SpeechZone(BaseModel):
    start: float
    end: float


class AudioFeatures(BaseModel):
    """音频特征：能量曲线（0.5s/点）、静音比、语音区（供 W8 消重降级）、BPM（可选）。"""

    energy_curve: list[list[float]] = Field(default_factory=list)  # [[t, rms], ...]
    silence_ratio: float = 0.0
    speech_zones: list[SpeechZone] = Field(default_factory=list)
    bpm: float | None = None


class EpisodeRawAnalysis(BaseModel):
    """单集第一层分析产出（api 层负责序列化落库）。"""

    asr_segments: list[AsrSegment] = Field(default_factory=list)
    scenes: list[SceneInfo] = Field(default_factory=list)
    audio: AudioFeatures = Field(default_factory=AudioFeatures)
