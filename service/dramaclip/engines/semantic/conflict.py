"""冲突打分（原案 4.2）：LLM 主路 + 关键词降级路。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment, SceneInfo
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable
from dramaclip.engines.semantic.models import ConflictScore

_SYSTEM_PROMPT = (
    "你是短剧剪辑顾问。对每个场景的冲突强度打分（0-100：0 平淡，100 激烈冲突/反转/高潮）。"
    '只返回 JSON 数组：[{"scene_index":0,"score":82,"reason":"简短理由"}]，'
    "scene_index 必须覆盖每个场景，不要输出其他内容。"
)

_CONFLICT_KEYWORDS: tuple[str, ...] = (
    "滚", "闭嘴", "混账", "畜生", "贱", "废物", "打死", "杀了", "报仇", "复仇", "背叛",
    "出轨", "离婚", "绝交", "证据", "真相", "欺骗", "骗子", "威胁", "跪下", "后悔",
    "哭", "求你", "凭什么", "不可能", "整整", "竟然", "居然", "都怪", "毁掉", "完了",
)
_INTENSIFIERS: tuple[str, ...] = ("！", "？", "…", "!?", "?!")


def score_scenes(
    segments: list[AsrSegment],
    scenes: list[SceneInfo],
    client: LlmClient | None,
) -> list[ConflictScore]:
    """LLM 可用走主路；未配置/失败降级关键词。"""
    if not scenes:
        return []
    if client is not None:
        try:
            return _score_with_llm(segments, scenes, client)
        except LlmUnavailable:
            pass
    return _score_with_keywords(segments, scenes)


def _score_with_llm(
    segments: list[AsrSegment],
    scenes: list[SceneInfo],
    client: LlmClient,
) -> list[ConflictScore]:
    user_payload = [
        {
            "scene_index": index,
            "time": f"{scene.start:.1f}-{scene.end:.1f}s",
            "dialogue": [seg.text for seg in segments if _in_span(seg, scene)],
        }
        for index, scene in enumerate(scenes)
    ]
    import json

    raw = client.chat_json(_SYSTEM_PROMPT, json.dumps(user_payload, ensure_ascii=False))
    if not isinstance(raw, list):
        raise LlmUnavailable("冲突打分返回不是数组")
    by_index = {
        int(item["scene_index"]): item
        for item in raw
        if isinstance(item, dict) and "scene_index" in item and "score" in item
    }
    results: list[ConflictScore] = []
    for index, scene in enumerate(scenes):
        item = by_index.get(index)
        score = _clamp_score(item["score"]) if item else 50
        results.append(
            ConflictScore(
                scene_index=index,
                start=round(scene.start, 3),
                end=round(scene.end, 3),
                score=score,
                reason=str(item.get("reason", ""))[:100] if item else "",
            )
        )
    return results


def _score_with_keywords(
    segments: list[AsrSegment],
    scenes: list[SceneInfo],
) -> list[ConflictScore]:
    results: list[ConflictScore] = []
    for index, scene in enumerate(scenes):
        texts = [seg.text for seg in segments if _in_span(seg, scene)]
        joined = "".join(texts)
        keyword_hits = sum(joined.count(word) for word in _CONFLICT_KEYWORDS)
        punctuation_hits = sum(joined.count(mark) for mark in _INTENSIFIERS)
        raw = keyword_hits * 18 + punctuation_hits * 6
        score = _clamp_score(30 + raw) if joined else 20
        results.append(
            ConflictScore(
                scene_index=index,
                start=round(scene.start, 3),
                end=round(scene.end, 3),
                score=score,
                reason=f"关键词×{keyword_hits} 语气×{punctuation_hits}" if joined else "无对白",
            )
        )
    return results


def _in_span(segment: AsrSegment, scene: SceneInfo) -> bool:
    """段中点落在场景内即归属该场景。"""
    middle = (segment.start + segment.end) / 2
    return scene.start <= middle < scene.end


def _clamp_score(raw: object) -> int:
    try:
        return max(0, min(100, int(round(float(raw)))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 50
