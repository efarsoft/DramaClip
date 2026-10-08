"""AI 模式推荐（出片中心阶段①）：按题材与高光推 3 个模式，随项目缓存。

推荐一次算好存进项目设置（`mode_recommendation` 键），进页面秒出；「重新推荐」
显式刷新。LLM 未配置/失败/返回不合法时回退静态三件套——推荐纯按内容适配、
不强制掺「无需文案」保底位（模型稳定性由用户选型保障，业主裁决 2026-09-29）。
不足三个时按通用序补位并如实标注，保证预选框始终有三个可勾项。
"""

from __future__ import annotations

import json
import time
from typing import Any

from dramaclip.engines.narration.pipeline import MODE_LABELS
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo

_RECOMMEND_COUNT = 3
_CACHE_KEY = "mode_recommendation"
_TIMEOUT_S = 60.0
#: LLM 缺位时的静态组合与补位顺序：叙事强 → 节奏快 → 门槛最低，通用可用的次序。
_FALLBACK_ORDER = ["dialogue_narration", "cross_narration", "raw_clip"]

_MENU = "\n".join(f"- {mode}: {label}" for mode, label in MODE_LABELS.items())
_SYSTEM = (
    "你是短剧推广出片顾问。根据剧集的题材与高光信息，从模式菜单里挑出最"
    f"适合推广的 {_RECOMMEND_COUNT} 个模式，只输出 JSON："
    '{"modes": [{"mode": "模式id", "reason": "一句话理由，不超过15字，必须引用'
    '剧集内容依据（题材/反转/冲突密度），不许空泛"}]}。\n模式菜单：\n' + _MENU
)


def recommend(
    conn: Any, project_id: str, settings: dict[str, str], *, refresh: bool
) -> dict[str, Any]:
    """取推荐：有缓存且未要求刷新直接回；否则现算并写回项目设置。"""
    if not refresh:
        cached = projects_repo.get_settings(conn, project_id).get(_CACHE_KEY)
        if isinstance(cached, dict) and cached.get("modes"):
            return cached
    result = _compute(conn, project_id, settings)
    projects_repo.update_settings(conn, project_id, {_CACHE_KEY: result})
    return result


def _compute(conn: Any, project_id: str, settings: dict[str, str]) -> dict[str, Any]:
    episodes = episodes_repo.list_by_project(conn, project_id)
    genre, reasons = _content_facts(conn, [str(ep["id"]) for ep in episodes])
    modes = _ask_llm(settings, genre, reasons)
    return {"modes": modes, "genre": genre, "at": int(time.time() * 1000)}


def _content_facts(conn: Any, episode_ids: list[str]) -> tuple[str, list[str]]:
    """从各集分析记录里取推荐依据：题材（首个非空）+ 高光理由（跨集聚合，最多 6 条）。"""
    genre = ""
    reasons: list[str] = []
    for episode_id in episode_ids:
        record = analysis_repo.get(conn, episode_id)
        if record is None:
            continue
        if genre == "" and record["genre"]:
            genre = str(record["genre"])
        try:
            highlights = json.loads(record["highlights"] or "[]")
        except json.JSONDecodeError:
            continue
        for item in highlights[:2]:
            reason = str(item.get("reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if genre != "" and len(reasons) >= 6:
            break
    return genre, reasons[:6]


def _ask_llm(settings: dict[str, str], genre: str, reasons: list[str]) -> list[dict[str, str]]:
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        return _fallback([], "LLM 未配置")
    facts = [f"题材：{genre}"] if genre else []
    facts.extend(f"- {reason}" for reason in reasons)
    if len(facts) <= 1:
        facts.append("-（高光理由缺失，仅凭题材判断）")
    client = LlmClient(config, timeout_s=_TIMEOUT_S)
    try:
        raw = client.chat_json(_SYSTEM, "\n".join(facts))
    except LlmUnavailable as exc:
        return _fallback([], f"LLM 不可用（{exc}）")
    except Exception as exc:  # noqa: BLE001 - 返回不合法也是回退，不是异常
        return _fallback([], f"返回不合法（{type(exc).__name__}）")
    picked = _validate(raw)
    if not picked:
        return _fallback([], "AI 推荐结果不在模式菜单内，已换为通用推荐")
    return _pad(picked)


def _validate(raw: Any) -> list[dict[str, str]]:
    """筛出菜单内的合法模式（去重）；mode 兼容 id 或中文标签（LLM 偶尔
    返回「高光混剪」而非 highlight_cut，能唯一映射回 id 就不整条丢弃）。
    """
    out: list[dict[str, str]] = []
    label_to_id = {label: mode for mode, label in MODE_LABELS.items()}
    if not isinstance(raw, dict):
        return out
    for item in raw.get("modes") or []:
        if not isinstance(item, dict):
            continue
        mode = str(item.get("mode") or "").strip()
        mode = label_to_id.get(mode, mode)
        if mode not in MODE_LABELS or any(p["mode"] == mode for p in out):
            continue
        reason = str(item.get("reason") or "").strip()[:40] or str(MODE_LABELS[mode])
        out.append({"mode": mode, "reason": reason})
    return out[:_RECOMMEND_COUNT]


def _fallback(picked: list[dict[str, str]], reason: str) -> list[dict[str, str]]:
    """静态兜底：保留 LLM 给出的合法项，按通用序补足三个，补位如实标注。"""
    out = list(picked)
    for mode in _FALLBACK_ORDER:
        if len(out) >= _RECOMMEND_COUNT:
            break
        if any(p["mode"] == mode for p in out):
            continue
        out.append({"mode": mode, "reason": f"补位（{reason}）"})
    return out[:_RECOMMEND_COUNT]


def _pad(picked: list[dict[str, str]]) -> list[dict[str, str]]:
    return _fallback(picked, "LLM 只给出部分")
