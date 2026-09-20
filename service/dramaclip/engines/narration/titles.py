"""候选标题生成：读单条方案解说全文，LLM 产出多样化标题。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines import llm_prompts
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

_SYSTEM_PROMPT = (
    "你是短剧推广视频标题专家。根据解说文案生成 8 条候选视频标题，"
    "风格多样：钩子前置、悬念留白、数字冲击、身份反差各占一些，"
    "每条不超过 20 个字，忠于剧情、不夸大、不使用违规词；"
    "标题只抛悬念，严禁剧透最大反转或结局——观众知道答案就不会看完。"
    '只输出 JSON：{"titles": ["标题1", "标题2", ...]}'
)


def generate(
    plan_data: dict[str, Any],
    settings: dict[str, str],
    *,
    timeout_s: float = 120.0,
) -> list[dict[str, Any]]:
    """返回 [{text, selected}]；LLM 未配置或产出为空时抛异常，由调用方转译。"""
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable("LLM 未配置：候选标题由模型生成，请先在「引擎」页配置文本模型")
    texts = [str(t.get("text", "")) for t in plan_data.get("narration_texts", []) if t.get("text")]
    if not texts:
        raise ValueError("该方案没有解说文案，无需生成标题")
    client = LlmClient(config, timeout_s=timeout_s)
    data = client.chat_json(
        llm_prompts.system_override(settings, "prompt.titles_system") or _SYSTEM_PROMPT,
        "解说文案：\n" + "\n".join(texts),
    )
    raw = data.get("titles", []) if isinstance(data, dict) else []
    titles = [
        {"text": title.strip(), "selected": False}
        for title in raw
        if isinstance(title, str) and title.strip()
    ]
    if not titles:
        raise ValueError("模型未产出有效标题")
    return titles
