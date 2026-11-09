"""逐平台发布包：画幅/字数适配 + 实测话题注入 + 逐平台 AI 声明指引。

平台规格与话题库出处见 docs/research/2026-11-09-improvement-proposal.md
（竞品 G2 一手 + §2.2 四平台实测：#好剧推荐 ×70/#短剧推荐 ×36/
#因为一个片段看了整部剧 ×32/#短剧 ×32）。AI 声明指引是运营建议（二手），
法定隐式标识另走 export.aigc_metadata。标题全局上限已是 20 字
（titles._TITLE_MAX_CHARS），平台字数适配是校验而非截断。
"""

from __future__ import annotations

from typing import Any

#: 平台优先级按实测：抖音>视频号>快手；B站/小红书适配即可不重投入。
PLATFORM_ORDER = ("抖音", "视频号", "快手", "小红书", "B站")

PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "抖音": {
        "cover_ratio": (9, 16), "title_max": 20,
        "ai_declaration": "发布页勾选「内容由 AI 生成」声明入口（平台对 AI 合成内容有标注要求）",
    },
    "视频号": {
        "cover_ratio": (6, 7), "title_max": 20,
        "ai_declaration": "发布时勾选 AI 生成内容声明；未声明的 AI 内容平台可能自行加注",
    },
    "快手": {
        "cover_ratio": (9, 16), "title_max": 20,
        "ai_declaration": "发布页勾选 AI 生成声明入口",
    },
    "小红书": {
        "cover_ratio": (3, 4), "title_max": 20,
        "ai_declaration": "笔记设置勾选「内容疑似 AI 生成」声明",
    },
    "B站": {
        "cover_ratio": (16, 10), "title_max": 20,
        "ai_declaration": "投稿勾选创作声明中的「AI 生成」项",
    },
}

#: 实测高频话题（§2.2），注入顺序即频次降序。
MEASURED_TOPICS = ("好剧推荐", "短剧推荐", "因为一个片段看了整部剧", "短剧")
_TAG_CAP = 8


def inject_topics(tags: list[str]) -> list[str]:
    """LLM 标签尾部补实测高频话题（去重、帽 8）：槽满不注入，不挤掉用户标签。"""
    merged = list(tags)
    for topic in MEASURED_TOPICS:
        if len(merged) >= _TAG_CAP:
            break
        if topic not in merged:
            merged.append(topic)
    return merged


def build_pack(
    titles: list[dict[str, Any]], caption: str | None, tags: list[str]
) -> dict[str, Any]:
    """只读快照 → 逐平台包；选用标题优先，无选用取第一条。"""
    selected = next((str(t.get("text", "")) for t in titles if t.get("selected")), "")
    if not selected and titles:
        selected = str(titles[0].get("text", ""))
    merged_tags = inject_topics(tags)
    platforms: dict[str, Any] = {}
    for name in PLATFORM_ORDER:
        spec = PLATFORM_SPECS[name]
        platforms[name] = {
            "title": selected,
            "title_fits": len(selected) <= int(spec["title_max"]),
            "caption": caption,
            "tags": merged_tags,
            "cover_ratio": list(spec["cover_ratio"]),
            "ai_declaration": spec["ai_declaration"],
        }
    return {"title": selected, "caption": caption, "tags": merged_tags, "platforms": platforms}
