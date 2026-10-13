"""候选标题生成：读单条方案解说全文，LLM 产出多样化标题。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

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


def generate(
    plan_data: dict[str, Any],
    settings: dict[str, str],
    *,
    timeout_s: float = 120.0,
    trace_path: Path | None = None,
) -> dict[str, Any]:
    """返回 {titles: [{text, selected}], caption, tags}；LLM 未配置或标题为空时抛异常，
    由调用方转译。caption/tags 是同一往返顺带产出的发布物料，缺了不挡标题。"""
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable("LLM 未配置：候选标题由模型生成，请先在「引擎」页配置文本模型")
    texts = [str(t.get("text", "")) for t in plan_data.get("narration_texts", []) if t.get("text")]
    if not texts:
        raise ValueError("该方案没有解说文案，无需生成标题")
    client = LlmClient(config, timeout_s=timeout_s)
    system = llm_prompts.system_override(settings, "prompt.titles_system") or _SYSTEM_PROMPT
    user = "解说文案：\n" + "\n".join(texts)
    data = client.chat_json(system, user, temperature=0.75)
    raw = data.get("titles", []) if isinstance(data, dict) else []
    titles = [
        {"text": title.strip(), "selected": False}
        for title in raw
        if isinstance(title, str) and title.strip()
    ]
    caption = _clean_caption(data)
    tags = _clean_tags(data)
    # 判空抛出前先把往返落盘：标题忽好忽坏时，这是唯一能复盘的证据
    dump_trace(
        trace_path,
        {"engine": "titles", "system": system, "user": user, "raw": data, "accepted": len(titles)},
    )
    if not titles:
        raise ValueError("模型未产出有效标题")
    titles[0]["selected"] = True
    return {"titles": titles, "caption": caption, "tags": tags}


def _clean_caption(data: Any) -> str | None:
    caption = data.get("caption") if isinstance(data, dict) else None
    if not isinstance(caption, str):
        return None
    return caption.strip() or None


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
