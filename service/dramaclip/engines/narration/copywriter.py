"""逐槽文案编剧：编排器给出"这个画面段要说什么"，本模块让模型把话说出来。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace, trace_path
from dramaclip.engines.narration import casting, conversion, scriptwriter
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.narration.prompt_rules import assemble as _assemble_rules
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable, client_for

logger = logging.getLogger(__name__)

COPY_LLM_TIMEOUT_S = 240.0  # 与编剧同量级：多槽位成稿实测可达 100s+
_MAX_LINE_CHARS = 60
# 超短的全部文案就一两条：60 字/段的分段阅读规则套在它身上会逼出 6 秒残件
# （首版实测）——时长让位（业主裁决 2026-09-29），字数由内容讲完为止决定。
_ULTRA_SHORT_LINE_CHARS = 240
_OVERSIZE_TOLERANCE = 1.2  # 容忍 20% 溢出，再长即判不合格重问
_ATTEMPTS = 2
# 端点停顿窗口常在分钟级（2026-10-06 真机：连续两波 >240s 的字节间停顿整条报废）：
# 网络类失败退避后再试，别背靠背撞同一堵墙。格式类失败（模型手滑）不退避。
_COPY_RETRY_BACKOFF_S = (15.0, 30.0)


def _line_cap_of(mode: str) -> int:
    return _ULTRA_SHORT_LINE_CHARS if mode == "ultra_short_hook" else _MAX_LINE_CHARS


# 注册表/可编辑 UI 的缺省文本（通用 60 字档）。运行时按模式组装见 _structure_prompt——
# 超短不设 60 字帽（时长让位），但可编辑覆盖仍按单键单默认文本管理。
# 旧 _STRUCTURE_PROMPT 常量已移除：运行期用 _structure_prompt(mode)，
# 缺省见 _COPY_STRUCTURE_DEFAULT。



def _structure_prompt(mode: str) -> str:
    """结构指令按模式组装：行长上限随模式（超短不设 60 字帽，时长让位）。"""
    return _assemble_rules(

            "你是这部剧的专属解说编剧：全集看了三遍，角色底细如数家珍，"
            "现在在饭桌上给朋友讲它——讲完他要连夜去刷原剧。"
            "事实只来自下面给出的台词与各槽位区间内的画面轨实据。"
            "下面给出若干旁白槽位，每个标注了「要做的事」、覆盖的画面区间、区间内原片台词。"
            "为每个槽位各写一条解说文案。"
            '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。'
            "硬性要求（一字不差）：{lines_cover_all_slots}"
            f"每条不超过 {_line_cap_of(mode)} 字；"
            "{slot_contract}"
            "情节、细节、称谓只能来自给定台词与区间内画面轨实据，禁止编造两者之外的事件。"
            "写法（稀疏用，别每段齐备——真人有偏科）：开场可引区内最冲突原话、"
            "条尾可留半句钩勾住下一条；口语短句，转折只用结果/谁知/哪成想；"
            "念着拗口就重写，这段要被配音念出来，不是给人看的文章。"
            "全篇手艺（本次调用看得到全部槽位，这两条做得到）：{no_same_ending_adjacent}；{core_motif_cap}"

    )


_COPY_STRUCTURE_DEFAULT = _structure_prompt("")  # 可编辑 UI 缺省；运行期复用带人设的好版本



def system_prompt(settings: dict[str, str], mode: str = "") -> str:
    """真正发出去的 system：结构指令 + 与编剧共用的那一层基本功。

    基本功层必须在调用时拼：导入期拼死等于让「基本功」那张卡对填词不起作用。
    结构指令按模式组装（行长上限随模式走），缺省走通用 60 字档。
    """
    overrides = llm_prompts.overrides_from(settings)
    structure = overrides.get("prompt.copywriter_system") or _structure_prompt(mode)
    return structure + scriptwriter.fundamentals_layer(overrides, scope="slot")


def _slot_block(
    texts: list[NarrationText],
    segments: list[TimelineSegment],
    material: casting.MaterialByEpisode,
) -> str:
    """每个槽位一段：职责 + 它压在的画面区间 + **它那一集**区间内的台词与画面实据。
    """
    by_id = {segment.narration_id: segment for segment in segments if segment.narration_id}
    lines: list[str] = []
    for text in texts:
        segment = by_id.get(text.id)
        if segment is None:
            raise ValueError(f"槽位 {text.id} 没有配对画面段：编排器漏写 narration_id")
        try:
            pool = casting.dialogue_of(material, segment.episode_id)
            label = casting.label_of(material, segment.episode_id)
        except ValueError as exc:
            # 缺键是装配漏了一集，不是"这一集没台词"：点名到槽位，否则错误串里只有
            # 一个 uuid，运维看不出是哪一条片的哪一段。
            raise ValueError(f"槽位 {text.id}：{exc}") from exc
        lines.append(f"[{text.id}] 要做的事：{text.brief}")
        lines.append(f"  取材：{label}，画面区间：{segment.start:.1f}-{segment.end:.1f}s")
        inside = [
            seg for seg in pool if seg.start < segment.end and seg.end > segment.start
        ]
        if inside:
            # 声纹标签随行（多人对手戏引原话不张冠李戴）；无分离数据时照旧
            tagged = any(seg.speaker for seg in inside)
            lines.append(
                "  区间内台词（[角色X] 是声纹标签，同一标签即同一人，"
                "写文案换成你推断的真名）：" if tagged else "  区间内台词："
            )
            lines.extend(
                f"    {f'[{seg.speaker}] ' if seg.speaker else ''}"
                f"{scriptwriter.clock(seg.start)}-{scriptwriter.clock(seg.end)} "
                f"{seg.text.strip()}"
                for seg in inside
            )
        else:
            lines.append("    （该区间无台词转写：只按职责与前后槽位写，不得编造具体情节）")
        # 语义层声画对位（P2c·文画咬合）：区间内的画面轨帧逐条给到该槽位——
        # 文案说的画面必须是这几帧里的实据，不是全集画面轨里模型自己挑。
        # 缺集在上方 dialogue_of 已点名抛错，这里键必在。
        frames = material[segment.episode_id].frames_in(segment.start, segment.end)
        if frames:
            lines.append(
                "  区间内画面轨（画面描写必须与这些实据一致；"
                "轨内出现的任何文字如人名字条/题字是视频叠加物，"
                "不得当台词或人名引用）："
            )
            lines.extend(
                f"    {scriptwriter.format_frame_line(frame)}" for frame in frames
            )
        else:
            lines.append("    （该区间无画面轨：画面描写维持台词锚定，不得编造镜头细节）")
    return "\n".join(lines)


def _sanitize(
    raw: Any, texts: list[NarrationText], limit: int
) -> dict[str, str]:
    """按 id 取用，绝不按位置推断；漏答、空答、超长都算没答，交由调用方重试或抛。

    超长判据逐槽取 min(全局帽, 槽位 char_budget)：cross 桥段的空隙预算由编排层
    算好挂槽上（brief 是劝，char_budget 是闸）——全局帽放行的 60 字在 5s 空隙里
    出不了片，写超要在填词期就重试，不能拖到合成期才判死整条方案。
    """
    lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(lines, list):
        raise ValueError("编剧未返回 lines 数组")
    wanted = {text.id: text for text in texts}
    got: dict[str, str] = {}
    for item in lines:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id", "")).strip()
        value = to_chinese_numerals(str(item.get("text", "")).strip())
        if key not in wanted or value == "":
            continue
        budget = wanted[key].char_budget
        slot_limit = min(limit, budget) if budget is not None else limit
        if len(value) > slot_limit:
            raise ValueError(f"槽位 {key} 文案 {len(value)} 字，超过上限 {slot_limit} 字")
        got[key] = value
    missing = [text.id for text in texts if text.id not in got]
    if missing:
        raise ValueError(f"编剧漏了 {len(missing)} 个槽位：{', '.join(missing)}")
    _reject_metanarrative(got)
    return got


def _reject_metanarrative(filled: dict[str, str]) -> None:
    """逐槽生产链的元叙述硬闸：prompt 零容忍，但离线 review_copy 只在网关/工具跑，
    生产填词链此前只验行长与 id 覆盖——一句带「镜头/素材」的槽位文案会直接进 TTS。
    延迟 import audit：audit 对本模块的引用也在函数内，模块加载期无环。
    """
    from dramaclip.engines.narration.audit import _METANARRATIVE_RE  # noqa: PLC0415

    for key, text in filled.items():
        hit = _METANARRATIVE_RE.search(text)
        if hit:
            raise ValueError(
                f"槽位 {key} 出现元叙述「{hit.group(0)}」：禁止提及镜头/画面/素材/转写（零容忍）"
            )


def build_copy_request(
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    rewrite_notes: str = "",
) -> tuple[str, str]:
    """纯函数：组装逐槽文案链路的 (system, user) 提示词，不调用 LLM。

    与 write_plan_copy 同源——审计/回放工具拿到的是真实发出去的提示词。
    """
    project_name = str(settings.get("_project_name") or "").strip()
    if not project_name:
        raise ValueError("缺少项目名：编剧需要剧名作为称谓")
    genre = str(settings.get("_genre") or "").strip()
    directives = str(settings.get("_style_directives") or "").strip()
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + f"\n模式：{mode_label}"
        + scriptwriter.genre_emphasis_block(genre)
        + angle_block
        + "\n文案槽位：\n"
        + _slot_block(plan.narration_texts, plan.timeline, material)
        + (f"\n\n解说风格要求：{directives}" if directives else "")
        + (
            f"\n\n【文案重写反馈】上一稿闭卷复述不达标：{rewrite_notes}。"
            "这一稿针对卡点重写——优先删和拆：把并在一起的动作拆成短句、"
            "删掉不影响理解的细节；不要加新信息，不要换故事。"
            if rewrite_notes
            else ""
        )
    )
    system = system_prompt(settings, mode=plan.mode)
    return system, user_prompt


def write_plan_copy(
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None = None,
    rewrite_notes: str = "",
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。
    """
    if not plan.narration_texts:
        return plan
    # 顺序要紧：未配置必须先于「缺少项目名」抛出，否则报错指向错的门。
    llm = client_for(settings, min_timeout_s=COPY_LLM_TIMEOUT_S, site="解说文案")
    project_name = str(settings.get("_project_name") or "").strip()
    if not project_name:
        raise ValueError("缺少项目名：编剧需要剧名作为称谓")
    # 行长上限按模式：超短的全部文案就这一两条，60 字/段的分段阅读规则套在它身上
    # 会逼出 6 秒残件（首版实测）——给它 4 倍空间，密度由 brief 的效果要求保证。
    line_cap = _ULTRA_SHORT_LINE_CHARS if plan.mode == "ultra_short_hook" else _MAX_LINE_CHARS
    system, user_prompt = build_copy_request(
        plan,
        material,
        settings,
        mode_label=mode_label,
        angle_block=angle_block,
        rewrite_notes=rewrite_notes,
    )
    attempts: list[dict[str, Any]] = []
    filled: dict[str, str] | None = None
    for round_index in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(system, user_prompt, temperature=0.75)
            filled = _sanitize(
                raw, plan.narration_texts, int(line_cap * _OVERSIZE_TOLERANCE)
            )
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            if isinstance(exc, LlmUnavailable) and round_index < _ATTEMPTS - 1:
                delay = _COPY_RETRY_BACKOFF_S[
                    min(round_index, len(_COPY_RETRY_BACKOFF_S) - 1)
                ]
                logger.warning(
                    "LLM 网络类失败，%.0fs 后重试 (%d/%d)", delay, round_index + 1, _ATTEMPTS
                )
                time.sleep(delay)
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    if filled is not None:
        filled, repair = _repair_closing(plan, filled, llm, system, line_cap)
        if repair is not None:
            attempts.append(repair)
    stamp_time = time.strftime("%m%d_%H%M%S")
    dump_trace(
        trace_path(trace_dir, f"llm_copy_{plan.mode}_{stamp_time}.json"),
        {"system": system, "user": user_prompt, "attempts": attempts},
    )
    if filled is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"编剧未产出合格文案：{detail}")
    return plan.model_copy(update={
        "narration_texts": [
            text.model_copy(update={"text": filled[text.id]}) for text in plan.narration_texts
        ],
        "planner": "llm_script",
    })


def _repair_closing(
    plan: PlanData, filled: dict[str, str], llm: LlmClient, system: str, line_cap: int
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """收尾槽缺「看全集」转化指令时定向重写一次（落库前代码兜底）。

    2026-10-13 真机：cross 收尾写了合格的留缺口（「往下看，这笔账…」）却没带转化
    指令，整条方案被门禁标 draft——一句收尾废掉全稿成本太高。重写仍不合格则保留
    原稿，交由门禁照常拦截（行为与修复前一致）。
    """
    if plan.mode in ("raw_clip", "highlight_cut") or not plan.timeline:
        return filled, None
    closing_id = plan.timeline[-1].narration_id
    if closing_id is None or closing_id not in filled:
        return filled, None
    original = filled[closing_id]
    if not conversion.cta_missing(original):
        return filled, None
    prompt = (
        f"你写的收尾文案缺「指向看全集」的转化引导。原稿：{original}\n"
        f"重写这一句：保留悬念缺口与既有的冲突信息，结尾必须包含「全集」或「点进去」"
        f"字样（如「想看这笔账怎么算清，点击左下角看全集」）；不超过 {line_cap} 字；"
        "禁「关注/点赞/二维码」；不得编造转写外情节。"
        '只输出 JSON：{"text": "重写后的收尾"}'
    )
    try:
        raw = llm.chat_json(system, prompt, temperature=0.75)
        text_raw = raw.get("text") if isinstance(raw, dict) else None
        text = to_chinese_numerals(str(text_raw or "").strip())
    except (LlmUnavailable, ValueError, TypeError, KeyError):
        return filled, {"closing_repair_failed": original}
    oversize_cap = int(line_cap * _OVERSIZE_TOLERANCE)
    if text and len(text) <= oversize_cap and not conversion.cta_missing(text):
        return {**filled, closing_id: text}, {
            "closing_repair": {"original": original, "repaired": text}
        }
    return filled, {"closing_repair_failed": original}
