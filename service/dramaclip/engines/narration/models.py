"""编排数据模型（plan_data 统一结构，docs/service/02 §3）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AudioRole = Literal["original", "narration", "ducked"]


class TimelineSegment(BaseModel):
    """时间轴段：源集 + 起止 + 音频角色 + 转场 + 字幕指令（W7）。"""

    episode_id: str
    start: float
    end: float
    audio: AudioRole = "original"
    transition: Literal["cut", "fade", "black", "flash"] = "cut"
    subtitle_text: str | None = None
    emotion_label: str | None = None
    # 本段旁白对应的 NarrationText.id：编排时由模式写入（与槽位一一配对），
    # TTS 回填时刷新、回退原声时清空。编剧据此读画面区间、导出侧据此取音，
    # 两处都禁止再靠位置索引推断。
    narration_id: str | None = None


class NarrationText(BaseModel):
    """旁白槽位：编排器定"这段画面要说什么"，编剧填 `text`，配音回填音频与时长。
    """

    id: str
    text: str = ""
    voice: str | None = None
    audio_path: str | None = None
    duration: float | None = None
    # 槽位职责，进编剧 prompt：如「原声之间的串联：承接上一幕、留下一幕的悬念」
    brief: str = ""


class StrategySpec(BaseModel):
    """推广策略（原案第五章；W4 内置默认，平台预设 W7 接入）。

    不设成片时长上下限：产品的裁决是「时长让位于质量」（2026-09-29 业主）——
    段长=实测音频时长（时长服从故事），掐着秒数做片只会牺牲叙事完整度。
    """

    platform: str = "douyin"


class PlanData(BaseModel):
    """narration_plans.plan_data 的结构化定义。"""

    mode: str
    timeline: list[TimelineSegment] = Field(default_factory=list)
    narration_texts: list[NarrationText] = Field(default_factory=list)
    strategy: StrategySpec = Field(default_factory=StrategySpec)
    # 编排来源：rule=规则预算（默认）；llm_script=LLM 剧本驱动
    planner: str = "rule"
    # 剧本清洗层丢掉的段数（未知集号/越界/重叠/空文案）：仅 llm_script 链会写，
    # 其余模式恒为 0。方案卡据此显示「剧本丢弃 N 段」，把悄悄变短讲成明账。
    dropped_segments: int = 0
