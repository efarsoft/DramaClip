"""语义层数据模型（落库结构对齐 docs/service/04 episode_analysis 列）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConflictScore(BaseModel):
    """单场景冲突打分（0-100）。"""

    scene_index: int
    start: float
    end: float
    score: int
    reason: str = ""


class HighlightSegment(BaseModel):
    """高光片段（跨层综合排序产出）。"""

    start: float
    end: float
    score: float
    reason: str = ""


class SemanticResult(BaseModel):
    """单集第二层产出。"""

    conflict_scores: list[ConflictScore] = Field(default_factory=list)
    highlights: list[HighlightSegment] = Field(default_factory=list)
    genre: str = ""
