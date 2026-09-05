"""语义层单集管线：第一层产出 → 冲突/题材/高光（LLM 失败全程降级，绝不抛出）。"""

from __future__ import annotations

from dramaclip.engines.analysis.models import EpisodeRawAnalysis
from dramaclip.engines.semantic import conflict, genre, ranker
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable, from_settings
from dramaclip.engines.semantic.models import SemanticResult


def build_client(settings: dict[str, str]) -> LlmClient | None:
    """配置齐全返回客户端（调用时才发请求）；未配置返回 None（直接降级）。"""
    config_client = from_settings(settings)
    return config_client if config_client._config.configured else None  # noqa: SLF001 - 同包边界


def enhance(
    raw: EpisodeRawAnalysis,
    settings: dict[str, str],
    *,
    top_ratio: float = 0.3,
) -> SemanticResult:
    """冲突打分 + 题材 + 高光排序。任何 LLM 异常都已在此降级，不向外抛。"""
    client = build_client(settings)
    try:
        scores = conflict.score_scenes(raw.asr_segments, raw.scenes, client)
    except LlmUnavailable:  # 双保险：降级路自身不应抛，防御未预期异常
        scores = conflict.score_scenes(raw.asr_segments, raw.scenes, None)
    full_text = "".join(seg.text for seg in raw.asr_segments)
    try:
        detected = genre.classify(full_text, client)
    except LlmUnavailable:
        detected = genre.classify(full_text, None)
    highlights = ranker.rank_highlights(scores, raw.audio, raw.asr_segments, top_ratio=top_ratio)
    return SemanticResult(conflict_scores=scores, highlights=highlights, genre=detected)
