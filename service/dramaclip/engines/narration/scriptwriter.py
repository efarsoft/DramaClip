"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

logger = logging.getLogger(__name__)

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2
# 清洗后正文段数硬门：system 写了 12-28 是软要求，模型偷懒给 8 段照样过——
# 低于此门触发强化重掷，三次仍不达标整条方案失败（宁掷勿滥，时长让位质量的姊妹裁决）。
_MIN_BODY_SEGMENTS = 12
_EPISODE_LINE_CAP = 80
_TOTAL_LINE_CAP = 500
_MIN_LINES_PER_EPISODE = 3  # 集数再多，每集也至少露面的保底线
_MAX_ATTEMPTS = 3  # 首次 + 最多 2 次重试：网关抖动与模型手滑都不该一次判死

# 重试注入的格式强化：原样重问等于期待模型原样再犯一遍。
_FORMAT_REINFORCEMENT = (
    "\n\n【格式强化】上一次输出不是合法 JSON 或结构不符合要求。"
    "请严格按要求只输出 JSON：不要 markdown 围栏、不要任何多余文字；"
    "每个片段必须含 episode/start/end/text，且 0 <= start < end，不得超过该集时间上界。"
)

# 基本功层（永远注入，不交给模型发挥）：平台验证过的解说手艺底线。
# 题材口味由口味层（风格 directives）差异化，与此处不重叠。
FUNDAMENTALS = (
    "\n\n【解说基本功——逐条强制遵守】\n"
    "交付目标：这是导看全集的推广片，不是剧情摘要、不是观后感。"
    "看完的人必须还想点进去看原片；最大反转扣在全集里，本片只给一半答案。\n"
    "视角与语言：全程口语化说书人视角；短句为主，单句不超过 15 字；"
    "禁止书面腔、总结腔（如「本剧讲述了…」），禁止空洞形容词堆砌。"
    "人称二选一并全篇统一：第三人称说书人（默认），或主角第一人称"
    "（重生/穿越类代入感更强）；禁止中途切换视角。\n"
    "人味纪律（这条最重要）：AI 味的本质是把话说得太满太齐——信息尽数调用、"
    "每段都总结收束、句式工整对称；真人讲八卦会偷懒、会跳、会有没说完的半句。"
    "写完默念一遍，凡是饭桌上讲八卦不会那么说的句子，重写。六条——"
    "① 禁书面连接词：然而/随即/顿时/缓缓/宛如/此刻，一个都不许出现；"
    "口语替代：结果/转头/当场/直接/好家伙/哪成想；"
    "② 禁工整对仗与排比：真人讲话没有对联，句长必须长短交错，连续两句等长即返工；"
    "③ 每两三段拉一次观众：「你敢信？」「换你你咋办？」「注意，是亲儿子」——"
    "第二人称拉扯是完播钩子，一段至多一次，多了就油；"
    "④ 禁套话与先否后肯：不仅…而且…、不是…而是…、既…又…、从…到…、"
    "值得注意的是、不得不说、毫无疑问、堪称、就在这时——零容忍，"
    "转折只用「结果/谁知/哪成想」这种真人口癖；"
    "⑤ 禁把话说满：允许没说完的半句、允许省略主语，禁止每段结尾都收束总结；"
    "段落长短必须参差——高潮段放开写，过渡段一句话就够，"
    "全稿念下来该有喘息和突兀，不许四平八稳；"
    "⑥ 起手去重、动作优先：连续两段不得同一主语或同一句式起手"
    "（「他…」「她…」「这个男人…」必须轮换）；"
    "写具体动作不写概括——「她把婚书扔进火里」，不是「她做出了疯狂举动」，"
    "禁止「此举/该行为/这一幕背后」式名词化指代。\n"
    "结构与节奏：第一段解说必须在前 3 秒抛出全片最大的悬念或反差——"
    "必须是具体事实（身份/生死/数字/当众打脸），禁止「他竟然…」式空钩。"
    "每段只讲一个信息点；段间递进靠内容本身（结果反转/行动升级），"
    "不要依赖固定衔接词——「更狠的是」这类起手全片至多一次。"
    "给 TTS 留表演空间：句子长短交错，关键揭晓前用短句或省略号制造停顿，"
    "配音的悬念感一半来自标点。"
    "正文必须是一条连续故事线：背景起因→冲突升级→高潮反转，后一段承接前一段，"
    "禁止跳跃拼凑不相关片段。善用「半句钩」：把关键揭晓切在段落边界，答案留在下一段开头。"
    "紧凑是指不灌水，不是砍完整度：冲突链条没铺开就收尾才是失败，"
    "片长服从故事——宁可有血有肉地写到十几分钟，不要干瘪压缩，也不要为空时长注水。\n"
    "选段纪律：相邻解说尽量压在同集、时间相接或因果相接的画面上；"
    "禁止无因果跳切拼盘。换场可以，跳切堆砌不行。\n"
    "内容纪律：所有情节、细节、台词必须来自转写内容，禁止编造转写外的事件或设定；"
    "优先引用最有画面感的具体细节（动作/冲突/原话），拒绝抽象概括。\n"
    "悬念管理：全片最大的反转不得提前剧透——关键信息延后到结尾前揭晓。"
    "观众想知道答案，但你每次只给一半：给足情绪，扣住关键信息。"
    "结尾必须留「想知道结局」的缺口，CTA 只准引导去看全集（可带剧名），"
    "禁止空喊关注、点赞、收藏、二维码。"
)

_STRUCTURE_PROMPT = (
    "你是短剧推广解说编剧。根据给定的带时间戳台词转写，"
    "输出一条推广解说视频的剧本 JSON，格式："
    '{"hook": "开场钩子(1-2句)", "segments": [{"episode": 集号整数, "start": 数字秒,'
    ' "end": 数字秒, "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。'
    "要求：1) 每个片段都必须带 episode，一个都不能漏；start/end 是该集内的相对秒，"
    "取自转写台词的时间区间，不得超过该集「本集台词截至」给出的上界；"
    "同一集内按时间递增且互不重叠：下一段的 start 不得早于前一段的 end；"
    "相邻片段优先同集连续时段，换集必须有因果（前集埋线→后集爆发），禁止无因果跳切；"
    "1.5) hook 必须含一个具体反差事实（身份/生死/数字），禁止「他竟然…」式空泛悬念；"
    "台词前的[角色X]是声纹聚类标签，同一标签就是同一个人：写文案时把它换成你从"
    "称呼与剧情推断出的真名（如 小明/姐姐/总栽），推断不出再保留原标签；"
    "关键台词可原样引用（加引号）增强真实感；善用具体数字（年份/金额/集数）制造冲击；"
    "cta 必须是三段式转化引导：剧情悬念半句（承接正文最后的缺口，不剧透最大反转）"
    "+ 行动指令「点击左下角」+ 观看引导（「免费观看全集」或「立即观看全集」，可带剧名）。"
    "例：『吊了八年的婚约，竟是她复仇的第一步——点击左下角，免费观看全集。』"
    "例：『她想低调，可龙魂不许——点击左下角，立即观看《剧名》全集。』"
    "禁止空喊关注/点赞/收藏，禁止只写「去看全集」这类没有悬念钩子的光秃引导，"
    "禁止剧透最大反转。"
    "2) 正文 12-28 段：把冲突链条完整铺开（起因→多轮升级→连环反转→高潮），"
    "段数不够就是没讲透；冲突没讲完写到上限，禁止为赶时长砍高潮；"
    "每段文案不超过 60 字；"
            "文案要像真人解说员开口说话：相邻两段禁止同一提示语起手"
            "（「更狠的是/万万没想到/谁能想到」这类起手式全稿至多出现一次），"
            "每段至少一处情绪词（怒/恨/慌/疼/疯）或一句人物原话引用，"
            "多用短句和具体动作，拒绝概括性陈述与排比复读；"
            "交稿前自查：全稿「不是…而是…」出现次数必须是零，"
            "相邻两段起手不得同主语，段落长短必须参差；"
    "3) 覆盖剧情完整钩子-冲突-反转弧线，看完必须还想点进去看原片；"
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


def _sanitize_episodes(raw: Any, durations: dict[int, float]) -> tuple[Script | None, int]:
    """跨集剧本清洗：未知集号丢弃、逐集去重叠、集内时间越界裁剪、最少段数。

    返回 (剧本, 钳制段数)：钳制是悄悄改数（负起点抬到 0、超长尾裁到集时长、
    重叠段起点后移），段数进留痕才能对上「剧本为什么变短了」这笔账。
    集时长缺失（<=0）等于没有上界可钳：只去重叠不裁尾，宁可放过也不整批丢光。
    """
    script = Script.model_validate(raw)
    kept: list[ScriptSegment] = []
    cursors: dict[int, float] = {}
    clamped = 0
    for segment in sorted(script.segments, key=lambda s: (s.episode, s.start)):
        if segment.episode not in durations:
            continue
        duration = durations[segment.episode]
        start = max(segment.start, cursors.get(segment.episode, 0.0))
        end = min(segment.end, duration) if duration > 0 else segment.end
        text = segment.text.strip()
        if end - start < 0.5 or text == "":
            continue
        updated = {"start": round(start, 2), "end": round(end, 2), "text": text}
        if updated["start"] != segment.start or updated["end"] != segment.end:
            clamped += 1
            logger.info(
                "剧本段钳制：第%d集 %s-%ss → %s-%ss",
                segment.episode,
                segment.start,
                segment.end,
                updated["start"],
                updated["end"],
            )
        kept.append(segment.model_copy(update=updated))
        cursors[segment.episode] = end
    if len(kept) < _MIN_SEGMENTS:
        return None, clamped
    dropped = len(script.segments) - len(kept)
    return (
        script.model_copy(update={"segments": kept, "dropped_segments": dropped}),
        clamped,
    )


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
            # 声纹聚类标签（说话人分离开启时才有）：编剧看到的是「谁在说」，
            # 真名化是它的活——业主不看素材，角色名只能由读台词的人（LLM）推断。
            speaker = str(seg.get("speaker") or "").strip()
            prefix = f"[{speaker}] " if speaker else ""
            rendered.append(f"{span} {prefix}{text}")
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
    min_segments: int | None = None,
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
        f"按 system 给定的段数区间给够段数，把冲突讲透、反转给足戏份。\n"
        f"铺垫果断压缩，绝不为赶时长删掉关键冲突或草草收尾。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + f"{style_block}"
    )
    system = system_prompt(prompts)
    # 薄稿硬门按集数推导：2 段/集（10 集→20 段，单集→2 段），LLM 偷懒给薄稿
    # 会触发强化重掷；下限跟着输入规模走，单集项目不被跨集的尺子误杀。
    floor = max(2, 2 * len(episode_inputs)) if min_segments is None else min_segments
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    for attempt in range(_MAX_ATTEMPTS):
        # 重试注入格式强化：原样重问等于期待模型原样再犯
        ask = user_prompt + _FORMAT_REINFORCEMENT if attempt > 0 else user_prompt
        if attempts and attempts[-1].get("rejected"):
            tail_note = (
                f"上一次你只写了 {attempts[-1]['rejected']}。"
                "每集的冲突都要铺开成段，段数不够能力就是不及格——这次必须给满段数。"
            )
            ask += "\n\n" + tail_note
        raw: Any = None
        try:
            raw = llm.chat_json(system, ask)
            _require_explicit_episode(raw, durations)
            script, clamped = _sanitize_episodes(raw, durations)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError) as exc:
            # 留痕必须带上异常类型：网关挂了与 schema 不合规是两件完全不同的事；
            # 坏响应原文一并留下——只记异常文案，排查时分不清模型到底写了什么。
            attempt_trace: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            if raw is not None:
                attempt_trace["raw"] = raw
            attempts.append(attempt_trace)
            continue
        attempts.append(
            {
                "raw": raw,
                "accepted": script is not None,
                "segments_kept": len(script.segments) if script is not None else 0,
                "segments_dropped": script.dropped_segments if script is not None else 0,
                "segments_clamped": clamped,
            }
        )
        if script is not None and len(script.segments) < floor:
            kept = len(script.segments)
            attempts[-1]["rejected"] = f"正文仅 {kept} 段（要求至少 {floor} 段）"
            script = None
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

