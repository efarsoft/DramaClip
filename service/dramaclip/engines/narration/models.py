"""编排数据模型（plan_data 统一结构，docs/service/02 §3）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AudioRole = Literal["original", "narration", "ducked"]


class TimelineSegment(BaseModel):
    """时间轴段：源集 + 起止 + 音频角色 + 转场。"""

    episode_id: str
    start: float
    end: float
    audio: AudioRole = "original"
    transition: Literal["cut", "fade", "black", "flash"] = "cut"


class NarrationText(BaseModel):
    """旁白文案段（intro 等模式的 TTS 输入）。"""

    id: str
    text: str
    voice: str | None = None
    audio_path: str | None = None
    duration: float | None = None


class StrategySpec(BaseModel):
    """推广策略（原案第五章；W4 内置默认，平台预设 W7 接入）。"""

    platform: str = "douyin"
    min_duration_s: float = 30.0
    max_duration_s: float = 120.0


class PlanData(BaseModel):
    """narration_plans.plan_data 的结构化定义。"""

    mode: str
    timeline: list[TimelineSegment] = Field(default_factory=list)
    narration_texts: list[NarrationText] = Field(default_factory=list)
    strategy: StrategySpec = Field(default_factory=StrategySpec)
