"""解说风格库：内置只读风格（resources，随版本走）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable
from dramaclip.infra.paths import resolve_resources_dir

FALLBACK_STYLE_ID = "general"
AUTO_STYLE_ID = "auto"

# 题材 → 风格映射（auto 匹配用；genre 来自语义层 classify，见 genre.GENRES）
_GENRE_STYLE_MAP: dict[str, str] = {
    "悬疑": "suspense",
    "复仇": "shuanggan",
    "逆袭": "shuanggan",
    "甜宠": "sweet",
    "家庭伦理": "emotional",
    "古装": "immersive",
    "都市": FALLBACK_STYLE_ID,
    "其他": FALLBACK_STYLE_ID,
}


@lru_cache(maxsize=1)
def _load_builtin() -> dict[str, dict[str, Any]]:
    styles: dict[str, dict[str, Any]] = {}
    styles_dir = resolve_resources_dir() / "narration-styles"
    if not styles_dir.is_dir():
        return styles
    for file in sorted(styles_dir.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("style_id"):
            styles[str(data["style_id"])] = data
    return styles


def list_styles() -> list[dict[str, Any]]:
    """全部内置风格（元信息 + 完整定义）。"""
    return list(_load_builtin().values())


def get_style(style_id: str | None) -> dict[str, Any]:
    """按 id 取风格；缺失回退通用风格，再缺失返回空指令兜底。"""
    styles = _load_builtin()
    if style_id is not None and style_id in styles:
        return styles[style_id]
    return styles.get(
        FALLBACK_STYLE_ID,
        {"style_id": FALLBACK_STYLE_ID, "name": "通用", "directives": ""},
    )


def resolve_style_id(preferred: str | None, genre: str | None = None) -> str:
    """解析最终风格 id。
    """
    styles = _load_builtin()
    if preferred is not None and preferred != AUTO_STYLE_ID and preferred in styles:
        return preferred
    mapped = _GENRE_STYLE_MAP.get(genre or "", FALLBACK_STYLE_ID)
    if mapped in styles:
        return mapped
    return FALLBACK_STYLE_ID


_SELECT_SYSTEM_PROMPT = (
    "你是短剧推广策略师。根据台词转写判断剧情题材与爽点，"
    "从风格库中选出最适合的解说风格。只输出 JSON："
    '{"style_id":"风格id","reason":"一句话理由"}，不要其他内容。'
    "reason 必须引用转写中至少一处具体细节（人物/事件/台词）作为判断依据，禁止空泛套话。"
)


def select_style_with_reason(
    llm: LlmClient,
    transcript: list[dict[str, Any]],
    *,
    max_lines: int = 40,
    system_prompt: str | None = None,
    trace_path: Path | None = None,
) -> tuple[str, str] | None:
    """口味层：LLM 读转写从风格库自选风格，返回 (style_id, reason)。
    """
    styles = _load_builtin()
    if not styles:
        return None
    menu = "\n".join(
        f"- {sid} {data.get('name', '')}：{data.get('desc', '')}"
        for sid, data in sorted(styles.items())
    )
    lines = [
        f"{float(item.get('start', 0)):.0f}s {str(item.get('text', '')).strip()}"
        for item in transcript
        if str(item.get('text', '')).strip()
    ][:max_lines]
    if not lines:
        return None
    user_prompt = f"风格库：\n{menu}\n\n台词转写节选：\n" + "\n".join(lines)
    system = system_prompt or _SELECT_SYSTEM_PROMPT
    raw: Any = None
    error = ""
    try:
        raw = llm.chat_json(system, user_prompt)
    except LlmUnavailable as exc:
        error = f"{type(exc).__name__}: {exc}"
    picked = str(raw.get("style_id", "")).strip() if isinstance(raw, dict) else ""
    reason = str(raw.get("reason", "")).strip() if isinstance(raw, dict) else ""
    accepted = picked in styles
    # 模型报库外风格 id 时界面只看到"按题材匹配"，留痕是唯一的解释
    dump_trace(
        trace_path,
        {
            "engine": "style_select",
            "system": system,
            "user": user_prompt,
            "raw": raw,
            "error": error,
            "style_id": picked,
            "accepted": accepted,
        },
    )
    if not accepted:
        return None
    return picked, reason or "剧情匹配"
