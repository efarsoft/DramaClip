"""B10 六维文案评分：一批方案一次 LLM 往返，产出排序信号 + 改进建议。

**软信号定位（业主红线）**：评分只做两件事——① 有分时给方案卡排序、
② 给每条方案一句具体改进建议。它**绝不**参与 grade/defects 硬门禁，
也绝不阻断任何现有流程：评分失败/缺失时调用方降级为现状顺序（api/narration.py）。

六维对齐 DramaClip 转化质量线（JJYB-13 印证）：开头 3 秒钩子力与收尾导看力
是信息流转化的两端，权重并列最高；节奏/情绪/冲突是留人中段；画面潜力是
素材可看性兜底。每维 1-10，prompt 每档带**行为锚点**（具体可观察的描述，
禁抽象形容词）——LLM 打分方差大，锚点是把方差压下来的唯一手段。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace, trace_path
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

SCORING_LLM_TIMEOUT_S = 240.0  # 与选题/成稿同量级：一次读整批方案的解说全文
_ATTEMPTS = 2

# 六维与权重：hook_power / cta_pull 并列最高（转化质量线的两端——开头留人、
# 收尾导看全集，正是 conversion.py 硬门禁盯的两个位置，软评分与其同轴）；
# conflict_clarity 次之（看不懂冲突则前四句全白给）；rhythm / emotion_curve
# 是留人中段；visual_potential 最低（画面主要由取材决定，文案只能间接影响它）。
WEIGHTS: dict[str, float] = {
    "hook_power": 0.25,
    "rhythm": 0.12,
    "emotion_curve": 0.12,
    "conflict_clarity": 0.16,
    "cta_pull": 0.25,
    "visual_potential": 0.10,
}
DIMENSIONS: tuple[str, ...] = tuple(WEIGHTS)

_SYSTEM_PROMPT = (
    "你是短剧推广片的文案评审。下面给出一组推广方案的解说文案（按 [方案 N] 编号），"
    "为每一条方案按六个维度打 1-10 分，并给一句具体改进建议。\n"
    "打分必须按**行为锚点**对号入座，禁止凭印象给分：\n"
    "【hook_power 开头钩子力】9=第一句就是具体反差事实（身份/生死/数字/当众打脸），"
    "观众 3 秒内知道要看什么冲突；7=前两句内出现具体冲突事件，但反差要读第二句才成立；"
    "5=开头是背景铺垫，第 3-4 句才碰到冲突；3=开头讲人物身份或环境，五句内没有事件；"
    "1=开头与正片冲突无关（寒暄、概述、报幕腔）。\n"
    "【rhythm 节奏与信息密度】9=每句都推进一个新事实或新转折，无重复信息，句长在两三秒口播档；"
    "7=多数句子推进剧情，至多一句可删的重复；5=信息推进但夹带两三句空泛评论；"
    "3=大段复述同一件事或堆形容词；1=通篇没有新增信息。\n"
    "【emotion_curve 情绪起伏】9=文案里有明确的压抑→爆发拐点，且拐点落在具体动作句上；"
    "7=有强弱对比但拐点略平；5=情绪单一强度贯穿；3=情绪与事件脱节（事件平淡文案喊激烈）；"
    "1=通篇平铺直叙无强弱变化。\n"
    "【conflict_clarity 冲突可懂度】9=不看原片也能说清谁和谁、为什么、赌注是什么；"
    "7=三方关系清楚，赌注要点一句脑补；5=看得出有冲突但人物关系要靠猜；"
    "3=只有情绪词没有具体对立；1=读完不知道冲突是什么。\n"
    "【cta_pull 收尾导看力】9=收尾一句口播把「完整版更狠」落在具体悬念上"
    "（点名未揭的反转/未出的结果），让人必须点进去；7=收尾指向看全集但悬念笼统；"
    "5=收尾有导看意图却夹带剧情总结，冲劲被摊薄；3=收尾是文案自然结束，无导看动作；"
    "1=收尾出现「关注我」「点赞」类平台违禁腔或与正片无关的话。\n"
    "【visual_potential 画面潜力】9=文案句句对应可拍画面（动作、对峙、场景可想象）；"
    "7=多数句子有画面，个别内心独白难拍；5=一半句子是抽象评论没有对应画面；"
    "3=文案主要靠旁白解释画面之外的信息；1=完全无法想象对应画面。\n"
    "改进建议（suggestion）必须具体到「改哪一句、怎么改」，用中文，"
    "例如「开头 5 秒才入题，把身份反差提到第一句」；禁止「建议优化文案」这类空话。"
    "每条方案都要给建议，好方案也给（指出还能更狠的一处）。\n"
    '只输出 JSON：{"scores": [{"index": 方案编号整数, '
    '"dims": {"hook_power": 分数, "rhythm": 分数, "emotion_curve": 分数, '
    '"conflict_clarity": 分数, "cta_pull": 分数, "visual_potential": 分数}, '
    '"suggestion": "一句具体改进建议"}]}，不要其他文字。'
)


def weighted_total(dims: dict[str, float]) -> float:
    """六维加权和（1-10 同尺度）；缺维按在场权重归一，不假装缺失维度满分。"""
    present = {dim: value for dim, value in dims.items() if dim in WEIGHTS}
    if not present:
        raise ValueError("没有任何合法维度，无法计算总分")
    mass = sum(WEIGHTS[dim] for dim in present)
    return round(sum(WEIGHTS[dim] * value for dim, value in present.items()) / mass, 2)


def _parse_dims(raw: Any) -> dict[str, float]:
    """钳 1-10、丢非数值、丢未知维度；全丢光则回空 dict（调用方整条丢弃）。"""
    if not isinstance(raw, dict):
        return {}
    dims: dict[str, float] = {}
    for dim in DIMENSIONS:
        value = raw.get(dim)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue  # 非数值（含 bool：True 是 int 子类，必须显式排除）
        dims[dim] = float(min(10, max(1, value)))
    return dims


def _parse_batch(raw: Any, expected: int) -> dict[int, dict[str, Any]]:
    """按 index 归位一批评分；越界 index 与零合法维度的条目整条丢弃。"""
    items = raw.get("scores") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("评分未返回 scores 数组")
    parsed: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= expected:
            continue
        dims = _parse_dims(item.get("dims"))
        if not dims:
            continue
        suggestion = item.get("suggestion")
        parsed[index] = {
            "dims": dims,
            "total": weighted_total(dims),
            "suggestion": str(suggestion).strip() if isinstance(suggestion, str) else "",
        }
    if not parsed:
        raise ValueError("评分未产出任何合法条目")
    return parsed


def format_variant(index: int, row: dict[str, Any]) -> str:
    """一条方案进评分 prompt 的措辞：角度名 + 解说全文（无解说模式给时间轴摘要）。"""
    plan = row.get("plan_data") or {}
    texts = [
        str(item.get("text", "")).strip()
        for item in plan.get("narration_texts", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    subtitles = [
        str(segment.get("subtitle_text", "")).strip()
        for segment in plan.get("timeline", [])
        if isinstance(segment, dict) and str(segment.get("subtitle_text") or "").strip()
    ]
    lines = texts or subtitles
    body = "\n".join(lines) if lines else "（无旁白文案，按时间轴结构与角度评估）"
    angle = str(row.get("angle") or "").strip()
    head = f"[方案 {index}]" + (f" 角度：{angle}" if angle else "")
    return f"{head}\n{body}"


def score_variants(
    rows: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    trace_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """一次 LLM 往返评一批方案；返回 {plan_id: {dims, total, suggestion}}。

    未配置抛 LlmUnavailable，产出全废抛 ValueError——两者都由调用方（api 层）
    catch 住降级，本模块不吞异常：留痕里 attempts 全是 error 就是失败的证据。
    """
    if not rows:
        return {}
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：文案评分由模型产出，请先在「引擎」页配置文本模型"
        )
    user_prompt = "\n\n".join(
        format_variant(index, row) for index, row in enumerate(rows, start=1)
    )
    client = LlmClient(config, timeout_s=SCORING_LLM_TIMEOUT_S)
    system = (
        llm_prompts.system_override(settings, "prompt.variant_scoring_system")
        or _SYSTEM_PROMPT
    )
    attempts: list[dict[str, Any]] = []
    scored: dict[int, dict[str, Any]] | None = None
    for _ in range(_ATTEMPTS):
        try:
            raw = client.chat_json(system, user_prompt)
            scored = _parse_batch(raw, expected=len(rows))
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": len(scored)})
        break
    stamp = time.strftime("%m%d_%H%M%S")
    dump_trace(
        trace_path(trace_dir, f"llm_variant_scoring_{stamp}.json"),
        {
            "engine": "variant_scoring",
            "system": system,
            "user": user_prompt,
            "attempts": attempts,
            "accepted": None if scored is None else len(scored),
        },
    )
    if scored is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"文案评分未产出可用结果：{detail}")
    return {str(rows[index - 1]["id"]): entry for index, entry in scored.items()}


def rank_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """软排序（纯函数）：有分在前按 total 降序，平局按 variant_index 升序确定性兜底。

    **无分保持现状**：一行分数都没有时原样返回入参（同序同对象）——list_plans
    的逐字节降级就靠这条；部分有分时，无分行沉底但相对原序不动（评分缺失
    不该让老方案互相换位置）。稳定排序用 sorted 的稳定性，不引入随机。
    """
    if not any(row.get("score_total") is not None for row in rows):
        return rows
    scored = [row for row in rows if row.get("score_total") is not None]
    unscored = [row for row in rows if row.get("score_total") is None]
    scored.sort(key=lambda row: (-float(row["score_total"]), int(row.get("variant_index") or 0)))
    return scored + unscored
