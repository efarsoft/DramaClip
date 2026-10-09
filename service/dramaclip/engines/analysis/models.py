"""分析引擎数据模型（跨进程边界，字段对齐 protocol/schemas/analysis.json）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WordSpan(BaseModel):
    """字/词级时间戳（whisper word_timestamps），供 OCR 字流对齐用。

    probability 是识别侧观测值：paraformer/funasr 不给字级概率，恒为默认 1.0
    （633/633 实测），故融合裁决不引用它——见 fusion 模块 docstring。
    """

    start: float
    end: float
    word: str
    probability: float = 1.0


class AsrSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str | None = None
    emotion: str | None = None
    words: list[WordSpan] = Field(default_factory=list)
    # 文本来源：None/asr=纯语音识别；ocr_fixed=含 OCR 补入的字；review=两通道短语级分歧
    source: str | None = None


class OcrSegment(BaseModel):
    """硬字幕条：OCR 对烧录字幕的机器读数，时间轴为字幕驻留区间。

    不是「人工校对文本」——艺术字/遮挡下 RapidOCR 的字形误读（崇桢、蛙虫、枚势滔失）
    在真机上占多数，故它只能供时间与补字，不能改写语音文本。
    """

    start: float
    end: float
    text: str
    conf: float = 1.0


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
    peak_dbfs: float | None = None
    clipping: bool = False
    # B9：librosa beat_track 的拍点时刻（秒，3 位小数，升序），供编排层节拍吸附。
    # 旧库记录没有这个字段：model_validate 默认空列表，天然兼容、不强制重分析。
    beats: list[float] = Field(default_factory=list)


class EpisodeRawAnalysis(BaseModel):
    """单集第一层分析产出（api 层负责序列化落库）。"""

    asr_segments: list[AsrSegment] = Field(default_factory=list)
    scenes: list[SceneInfo] = Field(default_factory=list)
    audio: AudioFeatures = Field(default_factory=AudioFeatures)
