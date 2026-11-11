"""逐平台发布包：画幅/字数适配 + 实测话题注入 + 逐平台 AI 声明指引 + 发布前自查清单。

平台规格与话题库出处见 docs/research/2026-11-09-improvement-proposal.md
（竞品 G2 一手 + §2.2 四平台实测：#好剧推荐 ×70/#短剧推荐 ×36/
#因为一个片段看了整部剧 ×32/#短剧 ×32）。AI 声明指引是运营建议（二手），
法定隐式标识另走 export.aigc_metadata。标题全局上限已是 20 字
（titles._TITLE_MAX_CHARS），平台字数适配是校验而非截断。

发布前自查清单（build_checklist）：授权/挂载/标题封面/全程剧名/话题组五动作。
授权覆盖/挂载链接/标题封面相符**工具无法代查**——只输出人工动作（诚实纪律：
不替用户证明授权，不假绿）。全程剧名/话题组两项可从当前配置与发布包如实判
「已满足」——剧名层开且剧名非空、话题组注入后非空。
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


#: 自查清单的五个动作项（顺序即展示顺序，不排序）。
#: label 只留动作主干（真值扫描盯这些字面量，折行会改发往前端/复制的字节——
#: 与 prompt_rules 同款纪律，单行成常量）；补充语境进 note，不塞进 label。
_CHECKLIST_AUTH = "☐ 授权覆盖：推广链接在本剧授权范围内"
_CHECKLIST_LINK = "☐ 挂载链接：发布前点进确认能落到本剧"
_CHECKLIST_MATCH = "☐ 标题封面相符：悬念可以，标题党不行"
_CHECKLIST_NAME = "☐ 全程剧名：推广切片出品方要求全程带剧名"
_CHECKLIST_TAGS = "☐ 话题组：发布时带上实测高频话题"
_AUTH_NOTE = "有效期与分发平台需人工确认，工具不代为证明授权"
_LINK_NOTE = "防死链，需人工点验，工具不代查"
_MATCH_NOTE = "核对发布页标题与封面与成片内容一致，需人工核对"
_NAME_NOTE = "开启「出片 → 剧名常驻层」，未开或剧名为空则不满足"
_TAGS_NOTE = "高频话题：#好剧推荐 #短剧推荐 #因为一个片段看了整部剧 #短剧；标签为空需补"


def build_checklist(
    pack: dict[str, Any],
    *,
    drama_name: str,
    drama_name_layer_enabled: bool,
) -> list[dict[str, Any]]:
    """发布前自查清单（纯函数，不触库/不触系统）。

    五项动作；「全程剧名」「话题组」两项依当前事实判 satisfied：
      - 全程剧名 = 剧名层开启 且 剧名非空（关闭/剧名空＝未满足，给开启提示）
      - 话题组 = 注入后标签非空（注入实测高频话题，正常总有值＝满足）
    授权/挂载/标题封面三项**永远人工**（satisfied=False）——工具不代查、不假绿。
    返回 {label, satisfied, note}：satisfied=True 的项 label 带「☑」，否则「☐」，
    note 空串=无补充。前端照搬即可，不自行判满足态（单一数据源在此）。
    """
    name_ok = drama_name_layer_enabled and drama_name.strip() != ""
    has_tags = len(pack.get("tags") or []) > 0
    items: list[dict[str, Any]] = [
        {"label": _CHECKLIST_AUTH, "satisfied": False, "note": _AUTH_NOTE},
        {"label": _CHECKLIST_LINK, "satisfied": False, "note": _LINK_NOTE},
        {"label": _CHECKLIST_MATCH, "satisfied": False, "note": _MATCH_NOTE},
        {
            "label": _CHECKLIST_NAME,
            "satisfied": name_ok,
            "note": "" if name_ok else _NAME_NOTE,
        },
        {
            "label": _CHECKLIST_TAGS,
            "satisfied": has_tags,
            "note": "" if has_tags else _TAGS_NOTE,
        },
    ]
    for item in items:
        label = str(item["label"]).lstrip("☐ ")
        item["label"] = ("☑ " if item["satisfied"] else "☐ ") + label
    return items
