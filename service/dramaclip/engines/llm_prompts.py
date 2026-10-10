"""可编辑 LLM 提示词登记表：默认值仍在各引擎模块，settings 只存覆盖。

键即 settings 表键（`prompt.*`）；重置 = 删除该键。新增可编辑提示词在
SPECS 登记一行，引擎函数以 `system_override` 取覆盖、模块常量兜底。

默认值按「模块路径 + 属性名」延迟取：本模块被各引擎 import，若在模块顶层
反过来 import 引擎就成环（mypy 判不出类型、运行时靠 import 顺序侥幸过关）。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

# 提示词原样进每一次 LLM 往返：不设上限等于让人一键撑爆上下文预算
MAX_PROMPT_CHARS = 20_000


class PromptSpec:
    def __init__(
        self,
        key: str,
        title: str,
        description: str,
        default_getter: Callable[[], str],
    ) -> None:
        self.key = key
        self.title = title
        self.description = description
        self.default_getter = default_getter

    @property
    def default(self) -> str:
        return self.default_getter()



def _default(module: str, name: str) -> Callable[[], str]:
    """延迟到读取时再 import：登记处因此不需要认识任何引擎模块。"""

    def read() -> str:
        return str(getattr(importlib.import_module(module), name))

    return read


SPECS: list[PromptSpec] = [
    PromptSpec(
        "prompt.genre_system",
        "题材分类",
        "分析层：判断短剧主导题材（失败自动降级关键词）",
        _default("dramaclip.engines.semantic.genre", "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.conflict_system",
        "冲突打分",
        "分析层：逐场景冲突强度评分，驱动选料排序",
        _default("dramaclip.engines.semantic.conflict", "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.style_select_system",
        "风格自选",
        "口味层：LLM 读转写从风格库选解说风格",
        _default("dramaclip.engines.narration.styles", "_SELECT_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.angles_system",
        "选题角度",
        "为一模式选出 K 条卖点互异的取材角度",
        _default("dramaclip.engines.narration.angles", "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.scriptwriter_system",
        "剧情解说·结构指令",
        "剧本 JSON 格式与段数/时间轴等结构要求；手艺底线在下面那张卡",
        _default("dramaclip.engines.narration.scriptwriter", "_STRUCTURE_PROMPT"),
    ),
    PromptSpec(
        "prompt.scriptwriter_fundamentals",
        "解说基本功（编剧与填词共用）",
        "说书人视角/半句钩/导看全集/片长服从故事等常驻手艺底线，两条成稿链路都拼上这一段",
        _default("dramaclip.engines.narration.scriptwriter", "FUNDAMENTALS"),
    ),
    PromptSpec(
        "prompt.copywriter_system",
        "逐槽填词·结构指令",
        "六槽位模式（片头/交叉/超短/全片/双人/独白）共用的槽位契约与硬性要求",
        _default("dramaclip.engines.narration.copywriter", "_COPY_STRUCTURE_DEFAULT"),
    ),
    PromptSpec(
        "prompt.titles_system",
        "候选标题",
        "成片信息流标题：8 条候选，让人点进去看全集",
        _default("dramaclip.engines.narration.titles", "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.variant_scoring_system",
        "方案评分",
        "六维行为锚点评分 + 一句具体改进建议（软信号：只排序，不参与门禁）",
        _default("dramaclip.engines.narration.variant_scoring", "_SYSTEM_PROMPT"),
    ),
]

SPEC_BY_KEY = {spec.key: spec for spec in SPECS}


def overrides_from(settings: dict[str, str]) -> dict[str, str]:
    """仅收集 SPECS 键的非空覆盖，供无 settings 的引擎函数透传。"""
    return {k: v for k, v in settings.items() if k in SPEC_BY_KEY and v}


def system_override(settings: dict[str, str], key: str) -> str | None:
    """settings 里的非空覆盖优先，否则返回 None（引擎用内置默认）。"""
    value = settings.get(key, "")
    return value if value else None
