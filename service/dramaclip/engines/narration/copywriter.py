"""逐槽文案编剧：编排器给出"这个画面段要说什么"，本模块让模型把话说出来。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace, trace_path
from dramaclip.engines.narration import casting, scriptwriter
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

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
_STRUCTURE_PROMPT = (
    "你是短剧推广解说编剧。下面给出若干旁白槽位，每个槽位标注了它承担的职责、"
    "覆盖的画面区间，以及该区间内的原片台词。为每个槽位各写一条解说文案。\n"
    '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。\n'
    f"硬性要求：lines 必须覆盖全部槽位 id（数量与 id 一字不差）；每条不超过 {_MAX_LINE_CHARS} 字；"
    "槽位的职责标注是契约：文案必须完成该槽位要做的事，不得答非所问；"
    "开场槽必须 3 秒内抛出具体反差事实，禁止「他竟然…」；"
    "收尾/CTA 槽必须留缺口并引导去看全集（可带剧名），禁止关注/点赞/二维码，禁止剧透最大反转；"
    "按给定顺序书写，相邻两条要能连读成一条故事线；鼓励在条尾留半句钩勾住下一条；"
    "情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件。"
)


def _structure_prompt(mode: str) -> str:
    """结构指令按模式组装：行长上限随模式（超短的字数由内容决定，不设 60 字帽）。"""
    return (
        # 身份先行（sepia persona 模板的实测结论：给骨架得到填表，给身份得到声音）
        "你是这部剧的专属解说编剧：全集你看了三遍，角色底细如数家珍，"
        "现在在饭桌上给朋友讲它——讲完他要连夜去刷原剧。"
        "身份是你的，怎么组织是你的自由；事实只来自下面给出的台词。\n"
        "下面给出若干旁白槽位，每个槽位标注了它承担的职责、"
        "覆盖的画面区间，以及该区间内的原片台词。为每个槽位各写一条解说文案。\n"
        '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。\n'
        f"硬性要求：lines 必须覆盖全部槽位 id（数量与 id 一字不差）；"
        f"每条不超过 {_line_cap_of(mode)} 字；"
        "槽位的职责标注是契约：文案必须完成该槽位要做的事，不得答非所问；"
        "开场槽必须 3 秒内抛出具体反差事实，禁止「他竟然…」；"
        "开场可直接引用区间内最冲突的原片台词（冲突前置——台词比转述狠）；"
        "收尾/CTA 槽必须留缺口并引导去看全集（可带剧名），禁止关注/点赞/二维码，禁止剧透最大反转；"
        "缺口可升级为「代价式」：暗示现在退出的损失（不看完你都会惦记），禁止编造不存在的情节；"
        "按给定顺序书写，相邻两条要能连读成一条故事线；鼓励在条尾留半句钩勾住下一条；"
        "写法要像人在饭桌上讲八卦：短句为主、长短交错、口语词优先（结果/当场/直接），"
        "禁书面连接词（然而/随即/顿时/缓缓/宛如）与先否后肯（不是…而是…），"
        "转折只用「结果/谁知/哪成想」；相邻两条不得同一主语起手，"
        "每条原话引用至多一处，数字一律写中文（两千斤/八年，不写 2,000），"
        "禁元叙述——「第X集」「画面里」「镜头」这类讲文件的字眼一个不许有，"
        "禁止每条结尾都收束总结——允许半句钩把答案留给下一条；每条写完默念一遍，"
        "念着拗口的句子重写——这段文字是要被配音念出来的，不是给人看的文章；"
        "情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件。"
    )


def system_prompt(settings: dict[str, str], mode: str = "") -> str:
    """真正发出去的 system：结构指令 + 与编剧共用的那一层基本功。

    基本功层必须在调用时拼：导入期拼死等于让「基本功」那张卡对填词不起作用。
    结构指令按模式组装（行长上限随模式走），缺省走通用 60 字档。
    """
    overrides = llm_prompts.overrides_from(settings)
    structure = overrides.get("prompt.copywriter_system") or _structure_prompt(mode)
    return structure + scriptwriter.fundamentals_layer(overrides)


def _slot_block(
    texts: list[NarrationText],
    segments: list[TimelineSegment],
    material: casting.MaterialByEpisode,
) -> str:
    """每个槽位一段：职责 + 它压在的画面区间 + **它那一集**区间内的台词。
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
            lines.append("  区间内台词：")
            lines.extend(
                f"    {scriptwriter.clock(seg.start)}-{scriptwriter.clock(seg.end)} "
                f"{seg.text.strip()}"
                for seg in inside
            )
        else:
            lines.append("    （该区间无台词转写：只按职责与前后槽位写，不得编造具体情节）")
    return "\n".join(lines)


def _sanitize(
    raw: Any, texts: list[NarrationText], limit: int
) -> dict[str, str]:
    """按 id 取用，绝不按位置推断；漏答、空答、超长都算没答，交由调用方重试或抛。"""
    lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(lines, list):
        raise ValueError("编剧未返回 lines 数组")
    wanted = {text.id for text in texts}
    got: dict[str, str] = {}
    for item in lines:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id", "")).strip()
        value = str(item.get("text", "")).strip()
        if key not in wanted or value == "":
            continue
        if len(value) > limit:
            raise ValueError(f"槽位 {key} 文案 {len(value)} 字，超过上限 {limit} 字")
        got[key] = value
    missing = [text.id for text in texts if text.id not in got]
    if missing:
        raise ValueError(f"编剧漏了 {len(missing)} 个槽位：{', '.join(missing)}")
    return got


def write_plan_copy(
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。
    """
    if not plan.narration_texts:
        return plan
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：解说文案必须由编剧模型产出（已取消模板兜底），请在「引擎」页配置文本模型"
        )
    project_name = str(settings.get("_project_name") or "").strip()
    if not project_name:
        raise ValueError("缺少项目名：编剧需要剧名作为称谓")
    line_cap = _line_cap_of(plan.mode)
    # 行长上限按模式：超短的全部文案就这一两条，60 字/段的分段阅读规则套在它身上
    # 会逼出 6 秒残件（首版实测）——给它 4 倍空间，密度由 brief 的效果要求保证。
    line_cap = _ULTRA_SHORT_LINE_CHARS if plan.mode == "ultra_short_hook" else _MAX_LINE_CHARS
    genre = str(settings.get("_genre") or "").strip()
    directives = str(settings.get("_style_directives") or "").strip()
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + f"\n模式：{mode_label}"
        + angle_block
        + "\n文案槽位：\n"
        + _slot_block(plan.narration_texts, plan.timeline, material)
        + (f"\n\n解说风格要求：{directives}" if directives else "")
    )
    llm = LlmClient(
        config, timeout_s=float(settings.get("llm.timeout_s") or COPY_LLM_TIMEOUT_S)
    )
    system = system_prompt(settings, mode=plan.mode)
    attempts: list[dict[str, Any]] = []
    filled: dict[str, str] | None = None
    for round_index in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(system, user_prompt)
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
