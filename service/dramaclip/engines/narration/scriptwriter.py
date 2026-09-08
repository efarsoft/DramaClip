"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。

剧本驱动模式（用户提案）：时长由文案与叙事完整度决定，预算仅作为
提示词里的目标区间；LLM 不可用或输出非法时返回 None，调用方降级
到规则预算编排。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2
_MAX_SEGMENTS = 10
_MAX_TRANSCRIPT_LINES = 150

_SYSTEM_PROMPT = (
    "你是短剧推广解说编剧。根据给定的带时间戳台词转写，"
    "输出一条推广解说视频的剧本 JSON，格式："
    '{"hook": "开场钩子(1-2句)", "segments": [{"start": 数字秒, "end": 数字秒,'
    ' "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。'
    "要求：1) start/end 必须取自转写台词的时间区间且按时间顺序；"
    "2) 3-8 段，每段文案不超过 60 字；3) 覆盖剧情完整钩子-冲突-反转弧线；"
    "4) 只输出 JSON，不要多余文字。"
)


class ScriptSegment(BaseModel):
    """剧本片段：源视频区间 + 对应解说文案。"""

    start: float
    end: float
    text: str


class Script(BaseModel):
    """解说剧本：钩子 + 正文片段 + 结尾引导。"""

    hook: str = Field(min_length=1)
    segments: list[ScriptSegment] = Field(min_length=_MIN_SEGMENTS, max_length=_MAX_SEGMENTS)
    cta: str = ""


def estimate_duration(text: str) -> float:
    """按文案字数估算 TTS 时长（合成后以实际音频时长回填）。"""
    return max(1.0, round(len(text) / _CHARS_PER_SECOND, 2))


def write_script(
    llm: LlmClient,
    transcript: list[dict[str, Any]],
    *,
    target_min_s: float,
    target_max_s: float,
    project_name: str,
    episode_duration_s: float,
) -> Script | None:
    """生成剧本；LLM 失败/输出非法返回 None（调用方降级规则编排）。"""
    transcript_text = _format_transcript(transcript)
    if transcript_text == "":
        return None
    user_prompt = (
        f"项目：{project_name}\n"
        f"目标时长：{target_min_s:.0f}-{target_max_s:.0f} 秒"
        f"（按剧情需要可略长，但不要超过 {target_max_s:.0f} 秒）\n"
        f"视频总长：{episode_duration_s:.0f} 秒\n"
        f"台词转写（秒）：\n{transcript_text}"
    )
    for _ in range(2):  # 失败重试一次
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            script = _sanitize(raw, episode_duration_s)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError):
            continue
        if script is not None:
            return script
    return None


def _format_transcript(transcript: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in transcript:
        start = float(item.get("start", 0))
        end = float(item.get("end", 0))
        text = str(item.get("text", "")).strip()
        if text == "":
            continue
        lines.append(f"{start:.1f}-{end:.1f}s {text}")
        if len(lines) >= _MAX_TRANSCRIPT_LINES:
            break
    return "\n".join(lines)


def _sanitize(raw: Any, episode_duration_s: float) -> Script | None:
    """校验并清洗 LLM 输出：排序、去重叠、越界裁剪、最少段数。"""
    script = Script.model_validate(raw)
    kept: list[ScriptSegment] = []
    cursor = 0.0
    for segment in sorted(script.segments, key=lambda s: s.start):
        start = max(segment.start, cursor)
        end = min(segment.end, episode_duration_s)
        text = segment.text.strip()
        if end - start < 0.5 or text == "":
            continue
        kept.append(ScriptSegment(start=round(start, 2), end=round(end, 2), text=text))
        cursor = end
    if len(kept) < _MIN_SEGMENTS:
        return None
    return script.model_copy(update={"segments": kept})
