"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2
_EPISODE_LINE_CAP = 80
_TOTAL_LINE_CAP = 500
_MIN_LINES_PER_EPISODE = 3  # 集数再多，每集也至少露面的保底线

# 基本功层（永远注入，不交给模型发挥）：平台验证过的解说手艺底线。
# 题材口味由口味层（风格 directives）差异化，与此处不重叠。
FUNDAMENTALS = (
    "\n\n【解说基本功——逐条强制遵守】\n"
    "视角与语言：全程口语化说书人视角；短句为主，单句不超过 15 字；"
    "禁止书面腔、总结腔（如「本剧讲述了…」），禁止空洞形容词堆砌。"
    "人称二选一并全篇统一：第三人称说书人（默认），或主角第一人称"
    "（重生/穿越类代入感更强）；禁止中途切换视角。\n"
    "结构与节奏：第一段解说必须在前 3 秒抛出全片最大的悬念或反差。"
    "每段只讲一个信息点；段间用「谁知」「直到」「更狠的是」等递进衔接，禁止流水账。"
    "正文必须是一条连续故事线：背景起因→冲突升级→高潮反转，后一段承接前一段，"
    "禁止跳跃拼凑不相关片段。善用「半句钩」：把关键揭晓切在段落边界，答案留在下一段开头。"
    "紧凑是指不灌水，不是砍完整度：冲突链条没铺开就收尾才是失败，"
    "宁可有血有肉地长，不要干瘪压缩。\n"
    "内容纪律：所有情节、细节、台词必须来自转写内容，禁止编造转写外的事件或设定；"
    "优先引用最有画面感的具体细节（动作/冲突/原话），拒绝抽象概括。\n"
    "悬念管理：全片最大的反转不得提前剧透——关键信息延后到结尾前揭晓。"
    "观众想知道答案，但你每次只给一半：给足情绪，扣住关键信息。"
    "结尾必须留「想知道结局」的缺口，配合引导语。"
)

_STRUCTURE_PROMPT = (
    "你是短剧推广解说编剧。根据给定的带时间戳台词转写，"
    "输出一条推广解说视频的剧本 JSON，格式："
    '{"hook": "开场钩子(1-2句)", "segments": [{"episode": 集号整数, "start": 数字秒,'
    ' "end": 数字秒, "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。'
    "要求：1) 每个片段都必须带 episode，一个都不能漏；start/end 是该集内的相对秒，"
    "取自转写台词的时间区间，不得超过该集「本集台词截至」给出的上界；"
    "同一集内按时间递增且互不重叠：下一段的 start 不得早于前一段的 end；"
    "1.5) hook 必须含一个具体反差事实（身份/生死/数字），禁止「他竟然…」式空泛悬念；"
    "关键台词可原样引用（加引号）增强真实感；善用具体数字（年份/金额/集数）制造冲击；"
    "cta 必须是转化引导：留剧情缺口并引导观看完整版，不得空喊关注。"
    "2) 正文 12-20 段：把冲突链条完整铺开（起因→多轮升级→连环反转→高潮），"
    "段数不够就是没讲透；每段文案不超过 60 字；"
    "3) 覆盖剧情完整钩子-冲突-反转弧线；"
    "4) 只输出 JSON，不要多余文字。"
)


def fundamentals_layer(prompts: dict[str, str] | None = None) -> str:
    """基本功层文本（编剧与逐槽填词共用这一张卡）。"""
    return (prompts or {}).get("prompt.scriptwriter_fundamentals") or FUNDAMENTALS


def system_prompt(prompts: dict[str, str] | None = None) -> str:
    """真正发出去的 system = 结构指令 + 基本功层，两层各自可覆盖、各自不吞对方。"""
    overrides = prompts or {}
    structure = overrides.get("prompt.scriptwriter_system") or _STRUCTURE_PROMPT
    return structure + fundamentals_layer(overrides)


class ScriptSegment(BaseModel):
    """剧本片段：源视频区间 + 对应解说文案（跨集时 episode 为集号）。"""

    episode: int = 1
    start: float
    end: float
    text: str


class Script(BaseModel):
    """解说剧本：钩子 + 正文片段 + 结尾引导。"""

    hook: str = Field(min_length=1)
    segments: list[ScriptSegment] = Field(min_length=_MIN_SEGMENTS)
    cta: str = ""
    # 清洗层吃掉的段数（未知集号/越界/重叠/空文案）：随剧本一路带到方案卡，
    # 界面据此说"剧本丢弃 N 段"，不再让方案看起来天生就这么长。
    dropped_segments: int = 0


def estimate_duration(text: str) -> float:
    """按文案字数估算 TTS 时长（合成后以实际音频时长回填）。"""
    return max(1.0, round(len(text) / _CHARS_PER_SECOND, 2))


def _require_explicit_episode(raw: Any, durations: dict[int, float]) -> None:
    """多集输入下缺 episode 等于把别的集的段落悄悄塞回第 1 集：宁可重试也不猜。"""
    if len(durations) < 2:
        return
    segments = raw.get("segments") if isinstance(raw, dict) else None
    if not isinstance(segments, list):
        return
    for segment in segments:
        if isinstance(segment, dict) and "episode" not in segment:
            raise ValueError(
                f"剧本片段缺 episode 集号（{segment.get('start', '?')}s 起那段）："
                "多集输入下无法安全归位"
            )


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
    dropped = len(script.segments) - len(kept)
    return script.model_copy(update={"segments": kept, "dropped_segments": dropped})


def clock(seconds: float) -> str:
    """秒 → MM:SS（转写展示用）：公开给 copywriter 复用，别再各抄一份。"""
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def transcript_sampling_quota(
    episode_count: int,
    *,
    total_cap: int = _TOTAL_LINE_CAP,
    episode_cap: int = _EPISODE_LINE_CAP,
) -> int:
    """跨集转写的每集摘录配额。
    """
    if episode_count <= 0:
        return 0
    return min(max(total_cap // episode_count, _MIN_LINES_PER_EPISODE), episode_cap)


def _pick_across(segments: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    """单集内跨头尾均匀取 quota 段（必含首段与尾段）。
    """
    if quota <= 0 or not segments:
        return []
    last = len(segments) - 1
    if last < quota:  # 配额够整集：一段不丢
        return list(segments)
    if quota == 1:
        return [segments[last]]  # 只能留一段时留集尾（钩子）
    indices = sorted({round(i * last / (quota - 1)) for i in range(quota)})
    return [segments[i] for i in indices]


def _transcript_note(
    *,
    episode_count: int,
    total_segments: int,
    quota: int,
    kept: int,
) -> str:
    """向模型交代看到的是配额摘录还是全量逐字；静默取样等于骗模型。"""
    dropped = max(total_segments - kept, 0)
    if dropped == 0:
        return f"\n（共 {episode_count} 集、{total_segments} 段转写，以下即全量逐字。）"
    return (
        f"\n（共 {episode_count} 集、{total_segments} 段转写；受上下文预算限制，"
        f"以下为每集跨头尾均匀摘录约 {quota} 段、合计 {kept} 段，另有约 {dropped} 段未列出。"
        "每集首尾台词均已保留，中间为等距抽样——"
        "请据此判断全剧故事线、以及各集在高潮曲线上的位置。）"
    )


def _episode_bound_note(segments: list[dict[str, Any]], duration: float) -> str:
    """把清洗层真正执行的时间上界告诉模型：藏住上界等于让模型盲写、再整段丢弃。"""
    ceiling = max(float(seg.get("end", 0)) for seg in segments)
    note = f"（本集台词截至 {clock(ceiling)}"
    if duration > 0:
        note += f"，全长 {clock(duration)}"
    return note + "）"


def format_transcript_episodes(
    episode_inputs: list[dict[str, Any]],
    *,
    total_cap: int = _TOTAL_LINE_CAP,
    episode_cap: int = _EPISODE_LINE_CAP,
) -> str:
    """把多集转写拼成带集号与时间戳的输入块：预算内每集都有代表，绝不按集号头部截断。
    """
    usable = [ep for ep in episode_inputs if ep.get("segments")]
    if not usable:
        return ""
    quota = transcript_sampling_quota(len(usable), total_cap=total_cap, episode_cap=episode_cap)
    lines: list[str] = []
    kept = 0
    for episode in usable:
        all_segments = list(episode["segments"])
        rendered: list[str] = []
        for seg in _pick_across(all_segments, quota):
            text = str(seg.get("text", "")).strip()
            if text == "":
                continue
            span = f"{clock(float(seg.get('start', 0)))}-{clock(float(seg.get('end', 0)))}"
            rendered.append(f"{span} {text}")
        if not rendered:  # 一行没进就不留孤立集标题
            continue
        lines.append(f"【第{int(episode['number'])}集】")
        lines.append(_episode_bound_note(all_segments, float(episode.get("duration") or 0.0)))
        lines.extend(rendered)
        kept += len(rendered)
    total_segments = sum(len(ep["segments"]) for ep in usable)
    lines.append(
        _transcript_note(
            episode_count=len(usable),
            total_segments=total_segments,
            quota=quota,
            kept=kept,
        )
    )
    return "\n".join(lines)


def write_script_episodes(
    llm: LlmClient,
    episode_inputs: list[dict[str, Any]],
    *,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    trace_path: Path | None = None,
    prompts: dict[str, str] | None = None,
) -> Script:
    """跨集剧本：读多集转写（每集一个「【第N集】」分组），产出带集号的跨集故事剧本。
    """
    durations = {
        int(episode["number"]): float(episode.get("duration") or 0.0)
        for episode in episode_inputs
    }
    transcript_block = format_transcript_episodes(episode_inputs)
    if not transcript_block:
        raise ValueError("编剧无米下锅：所有集都没有台词转写")
    cross_block = (
        "跨集叙事要求：转写按集分组（每组以「【第N集】」单独一行开头，"
        "下一行给出该集的时间上界），其后每行一条台词，格式为「开始-结束 台词」，"
        "时间为该集内的相对时间。"
        "受上下文预算限制，每组是该集跨头尾的均匀摘录（集首与集尾台词必定保留），"
        "不是该集全量逐字。"
        "1) 片段结构按 system 要求 1)：episode 逐段必填，start/end 用各集自己的相对秒，"
        "禁止把多集拼成一条连续时间轴；"
        "2) 按剧情逻辑排序：铺垫在前、冲突升级居中、反转/高潮在后，可在不同集之间选取；"
        "3) 同一片段的画面必须取自同一集，同一集内按时间顺序。"
    )
    style_block = f"\n解说风格要求：{style_directives}" if style_directives != "" else ""
    user_prompt = (
        f"项目：{project_name}\n"
        f"时长不设上限：按 system 给定的段数区间给够段数，把冲突讲透、反转给足戏份。\n"
        f"铺垫果断压缩，但绝不为了控制时长删掉关键冲突或草草收尾。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + f"{style_block}"
    )
    system = system_prompt(prompts)
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    for _ in range(2):  # 失败重试一次
        try:
            raw = llm.chat_json(system, user_prompt)
            _require_explicit_episode(raw, durations)
            script = _sanitize_episodes(raw, durations)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError) as exc:
            # 留痕必须带上异常类型：网关挂了与 schema 不合规是两件完全不同的事
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append(
            {
                "raw": raw,
                "accepted": script is not None,
                "segments_kept": len(script.segments) if script is not None else 0,
                "segments_dropped": script.dropped_segments if script is not None else 0,
            }
        )
        if script is not None:
            break
    dump_trace(
        trace_path,
        {"system": system, "user": user_prompt, "attempts": attempts},
    )
    if script is None:
        detail = "；".join(str(item.get("error", "清洗后片段不足")) for item in attempts)
        raise ValueError(
            f"编剧未产出合法剧本（{len(attempts)} 次尝试）：{detail}"
            + (f"；完整往返见 {trace_path}" if trace_path else "")
        )
    return script

