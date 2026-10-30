"""候选标题生成：读单条方案解说全文，LLM 产出多样化标题。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import client_for

TITLES_LLM_TIMEOUT_S = 120.0  # 一条方案解说全文进、8 条标题出：与选题/金句同量级

_SYSTEM_PROMPT = (
    "你是短剧推广视频标题专家，负责成片的发布包装。根据解说文案产出三样发布物料。"
    "①titles：8 条候选视频标题（信息流标题+封面字层双用途），让人忍不住点进去看全集，不是剧情剧透。"
    "句式在六类实证套路里换着来：冲突一句话（身份反差+具体动作）、悬念反问（两难选择）、"
    "金句宣言（一句情绪共鸣收感叹号）、行为指令（预设观看反应）、"
    "人物关系三段式（人设+关系+情绪递进）、极简剧名式（人物+困境一短句）。"
    "示例只示范句式与节奏（「老板假装顾客视察却被员工羞辱」「先谋生，还是先谋爱？」"
    "「看这集的时候小点声笑，容易梦醒」「高冷校霸和乖乖女，双向暗恋，爱意疯长」），"
    "内容必须从本片解说文案里长出来，禁止照抄示例。"
    "每条不超过 20 个字，忠于剧情、不夸大、不使用违规词；"
    "标题只抛悬念，严禁剧透最大反转或结局——观众知道答案就不会点进去；"
    "可带剧名或人物身份，禁止「关注我」「第一集完整版免费」这类平台违禁腔。"
    "②caption：一条发布文案，1~2 句口语短句——先一句钩子或金句，再一句留缺口引导追剧；"
    "不超过 40 字，禁剧透反转、禁违禁腔。"
    "③tags：6~8 个话题标签（不带 # 号）：按剧情贴切挑题材情绪标签（如 爽剧/逆袭/悬疑/氛围感），"
    "配 2~3 个高流量行为标签（如 一口气看完、因为一个片段看了整部剧、热门短剧推荐、短剧推荐）。"
    '只输出 JSON：{"titles": ["标题1", ...], "caption": "发布文案", "tags": ["标签1", ...]}'
)

# prompt 承诺的硬约束（≤20 字/违禁腔），此前只有嘴上约定没有验收——LLM 遵从率
# 不稳，超长与违禁腔漏出去就是发布端事故。与 prompt 同表，出界剔除后如实交剩余。
_TITLE_MAX_CHARS = 20
_CAPTION_MAX_CHARS = 40
_BANNED_PHRASES = ("关注我", "点赞", "收藏", "订阅", "二维码", "第一集完整版", "免费")


def _passes_title_gate(text: str) -> bool:
    """单条标题验收：超长/违禁腔剔除（剧透无法机检，仍靠 prompt 与人工挑选）。"""
    if len(text) > _TITLE_MAX_CHARS:
        return False
    return not any(phrase in text for phrase in _BANNED_PHRASES)


def generate(
    plan_data: dict[str, Any],
    settings: dict[str, str],
    *,
    min_timeout_s: float = TITLES_LLM_TIMEOUT_S,
    trace_path: Path | None = None,
    project_brief: str | None = None,
    visual_hooks: list[str] | None = None,
) -> dict[str, Any]:
    """返回 {titles: [{text, selected}], caption, tags}；LLM 未配置或标题为空时抛异常，
    由调用方转译。caption/tags 是同一往返顺带产出的发布物料，缺了不挡标题。

    `min_timeout_s` 是下限：界面设的 `llm.timeout_s` 只能把它抬高。

    零文案模式（纯原片剪辑/金句流）没有 narration_texts：内容依据退到时间轴
    金句字幕（金句流）与 project_brief（剧名/角度，api 层组装）——标题规则
    与解说链完全一致，只换内容依据。两头都空仍然抛（此前行为）。

    `visual_hooks`：VL 高 watch_score 帧的画面描述（api 层从 visual_track 收集），
    标题生成注入画面亮点——标题可以具体到画面（"她把婚书扔进火里的那一刻"），
    不再纯文字抽象悬念。
    """
    client = client_for(settings, min_timeout_s=min_timeout_s, site="候选标题")
    texts = [str(t.get("text", "")) for t in plan_data.get("narration_texts", []) if t.get("text")]
    # 零文案模式（纯原片剪辑/金句流）没有 narration_texts：内容依据退到时间轴
    # 金句字幕（金句流）与 project_brief（剧名/角度，api 层组装）——标题规则
    # （不剧透/不违禁/≤20 字）与解说链完全一致，只换内容依据。
    golden = [
        str(segment.get("subtitle_text", "")).strip()
        for segment in plan_data.get("timeline", [])
        if str(segment.get("subtitle_text") or "").strip()
    ]
    if not texts and not golden and not project_brief:
        raise ValueError("该方案没有解说文案，无需生成标题")
    visual_block = ""
    if visual_hooks:
        visual_block = (
            "\n画面亮点（VL 看到的最有冲击力的画面——标题若能具体到这些画面，点击率更高）：\n"
            + "\n".join(f"- {line}" for line in visual_hooks)
        )
    system = llm_prompts.system_override(settings, "prompt.titles_system") or _SYSTEM_PROMPT
    if texts:
        user = "解说文案：\n" + "\n".join(texts) + visual_block
    elif golden:
        user = (
            "这是一条**原声金句合集**推广视频（无解说，画面配原声台词字幕）。"
            "标题与发布文案从这些金句的冲突与情绪出发，"
            "忠于台词呈现的剧情，禁止编造台词之外的情节。\n金句台词：\n"
            + "\n".join(f"- {line}" for line in golden[:12])
            + visual_block
        )
    else:
        user = (
            "这是一条**纯原片高光合集**推广视频（无解说无字幕，只有原声对白画面）。"
            "标题与发布文案从剧名与取材角度出发：忠于给定信息，"
            "禁止编造具体桥段与台词。\n影片信息：\n" + (project_brief or "")
            + visual_block
        )
    data = client.chat_json(system, user, temperature=0.75)
    raw = data.get("titles", []) if isinstance(data, dict) else []
    candidates = [
        title.strip() for title in raw if isinstance(title, str) and title.strip()
    ]
    titles = [
        {"text": title, "selected": False}
        for title in candidates
        if _passes_title_gate(title)
    ]
    rejected = len(candidates) - len(titles)
    caption = _clean_caption(data)
    tags = _clean_tags(data)
    # 判空抛出前先把往返落盘：标题忽好忽坏时，这是唯一能复盘的证据
    dump_trace(
        trace_path,
        {
            "engine": "titles", "system": system, "user": user, "raw": data,
            "accepted": len(titles), "gate_rejected": rejected,
        },
    )
    if not titles:
        raise ValueError(
            f"模型未产出有效标题（候选 {len(candidates)} 条全部超长或含违禁腔）"
            if candidates
            else "模型未产出有效标题"
        )
    titles[0]["selected"] = True
    return {"titles": titles, "caption": caption, "tags": tags}


def _clean_caption(data: Any) -> str | None:
    caption = data.get("caption") if isinstance(data, dict) else None
    if not isinstance(caption, str):
        return None
    clean = caption.strip()
    # caption 缺了不挡标题（docstring 契约），但超长/违禁的宁缺毋滥
    if not clean or len(clean) > _CAPTION_MAX_CHARS:
        return None
    if any(phrase in clean for phrase in _BANNED_PHRASES):
        return None
    return clean


def _clean_tags(data: Any) -> list[str]:
    """标签去 #、去空、去重；老输出没有 tags 字段时安静给空表。"""
    raw = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for tag in raw:
        clean = str(tag).strip().lstrip("#").strip() if isinstance(tag, str) else ""
        if clean and clean not in tags:
            tags.append(clean)
    return tags[:8]
