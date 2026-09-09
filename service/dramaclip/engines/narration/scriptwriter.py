"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。

剧本驱动模式（用户提案）：时长由文案与叙事完整度决定，预算仅作为
提示词里的目标区间；LLM 不可用或输出非法时返回 None，调用方降级
到规则预算编排。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2
_MAX_SEGMENTS = 10
_EPISODE_LINE_CAP = 80
_TOTAL_LINE_CAP = 500

# 基本功层（永远注入，不交给模型发挥）：平台验证过的解说手艺底线。
# 题材口味由口味层（风格 directives）差异化，与此处不重叠。
_FUNDAMENTALS = (
    "\n\n【解说基本功——逐条强制遵守】\n"
    "视角与语言：全程口语化说书人视角；短句为主，单句不超过 15 字；"
    "禁止书面腔、总结腔（如「本剧讲述了…」），禁止空洞形容词堆砌。"
    "人称二选一并全篇统一：第三人称说书人（默认），或主角第一人称"
    "（重生/穿越类代入感更强）；禁止中途切换视角。\n"
    "结构与节奏：第一段解说必须在前 3 秒抛出全片最大的悬念或反差。"
    "每段只讲一个信息点；段间用「谁知」「直到」「更狠的是」等递进衔接，禁止流水账。"
    "正文必须是一条连续故事线：背景起因→冲突升级→高潮反转，后一段承接前一段，"
    "禁止跳跃拼凑不相关片段。善用「半句钩」：把关键揭晓切在段落边界，答案留在下一段开头。"
    "节奏紧凑，但参考时长只是粗略锚点：剧情完整与冲突张力优先，宁可有血有肉地略长，不要干瘪压缩。\n"
    "内容纪律：所有情节、细节、台词必须来自转写内容，禁止编造转写外的事件或设定；"
    "优先引用最有画面感的具体细节（动作/冲突/原话），拒绝抽象概括。\n"
    "悬念管理：全片最大的反转不得提前剧透——关键信息延后到结尾前揭晓。"
    "观众想知道答案，但你每次只给一半：给足情绪，扣住关键信息。"
    "结尾必须留「想知道结局」的缺口，配合引导语。"
)

_SYSTEM_PROMPT = (
    "你是短剧推广解说编剧。根据给定的带时间戳台词转写，"
    "输出一条推广解说视频的剧本 JSON，格式："
    '{"hook": "开场钩子(1-2句)", "segments": [{"start": 数字秒, "end": 数字秒,'
    ' "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。'
    "要求：1) start/end 必须取自转写台词的时间区间且按时间顺序；"
    "2) 4-10 段，每段文案不超过 60 字；3) 覆盖剧情完整钩子-冲突-反转弧线；"
    "4) 只输出 JSON，不要多余文字。"
    + _FUNDAMENTALS
)


class ScriptSegment(BaseModel):
    """剧本片段：源视频区间 + 对应解说文案（跨集时 episode 为集号）。"""

    episode: int = 1
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


def _sanitize_episodes(raw: Any, durations: dict[int, float]) -> Script | None:
    """跨集剧本清洗：未知集号丢弃、逐集去重叠、集内时间越界裁剪、最少段数。"""
    script = Script.model_validate(raw)
    kept: list[ScriptSegment] = []
    cursors: dict[int, float] = {}
    for segment in sorted(script.segments, key=lambda s: (s.episode, s.start)):
        if segment.episode not in durations:
            continue
        duration = durations[segment.episode]
        start = max(segment.start, cursors.get(segment.episode, 0.0))
        end = min(segment.end, duration)
        text = segment.text.strip()
        if end - start < 0.5 or text == "":
            continue
        updated = {"start": round(start, 2), "end": round(end, 2), "text": text}
        kept.append(segment.model_copy(update=updated))
        cursors[segment.episode] = end
    if len(kept) < _MIN_SEGMENTS:
        return None
    return script.model_copy(update={"segments": kept})


def _clock(seconds: float) -> str:
    """秒 → MM:SS（转写展示用）。"""
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def write_script_episodes(
    llm: LlmClient,
    episode_inputs: list[dict[str, Any]],
    *,
    target_min_s: float,
    target_max_s: float,
    project_name: str,
    style_directives: str = "",
    trace_path: Path | None = None,
) -> Script | None:
    """跨集剧本：读多集转写（行首带集号），产出带集号的跨集故事剧本。

    episode_inputs 每项：{"number": 集号, "duration": 集时长秒,
    "segments": [{"start", "end", "text"}]}。失败返回 None，调用方降级规则编排。
    """
    durations: dict[int, float] = {}
    lines: list[str] = []
    for episode in episode_inputs:
        number = int(episode["number"])
        durations[number] = float(episode.get("duration") or 0.0)
        lines.append(f"第{number}集：")
        for count, seg in enumerate(episode["segments"]):
            if count >= _EPISODE_LINE_CAP or len(lines) >= _TOTAL_LINE_CAP:
                break
            text = str(seg.get("text", "")).strip()
            if text == "":
                continue
            span = f"{_clock(float(seg.get('start', 0)))}-{_clock(float(seg.get('end', 0)))}"
            lines.append(f"{span} {text}")
    if not lines:
        return None
    cross_block = (
        "跨集叙事要求：转写按集分组（每组以「第N集：」开头），"
        "每行一条台词，格式为「开始-结束 台词」，时间为该集内的相对时间。"
        "1) 每个片段必须带 episode 字段（集号整数），start/end 为该集内的相对秒，"
        "且必须落在某一行转写的时间区间内或其邻近处；"
        "2) 按剧情逻辑排序：铺垫在前、冲突升级居中、反转/高潮在后，可在不同集之间选取；"
        "3) 同一片段的画面必须取自同一集，同一集内按时间顺序。"
    )
    style_block = f"\n解说风格要求：{style_directives}" if style_directives != "" else ""
    user_prompt = (
        f"项目：{project_name}\n"
        f"参考时长：{target_min_s:.0f}-{target_max_s:.0f} 秒（仅作参考，不是硬限制）。\n"
        f"最高优先级是剧情完整与吸引力：铺垫果断压缩，冲突和反转给足戏份；"
        f"宁可略长，也不要为凑时长删掉关键冲突。\n"
        f"{cross_block}\n"
        f"台词转写：\n" + "\n".join(lines)
        + f"{style_block}"
    )
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    for _ in range(2):  # 失败重试一次
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            script = _sanitize_episodes(raw, durations)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": str(exc)})
            continue
        attempts.append(
            {
                "raw": raw,
                "accepted": script is not None,
                "segments_kept": len(script.segments) if script is not None else 0,
            }
        )
        if script is not None:
            break
    if trace_path is not None:
        _dump_trace(
            trace_path,
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    return script


def _dump_trace(path: Path, payload: dict[str, Any]) -> None:
    """LLM 调用全量留痕（system/user/原始响应），供人工检查。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass


