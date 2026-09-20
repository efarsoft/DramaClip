"""可编辑 LLM 提示词登记表：默认值仍在各引擎模块，settings 只存覆盖。

键即 settings 表键（`prompt.*`）；重置 = 删除该键。新增可编辑提示词在
SPECS 登记一行，引擎函数以 `system_override` 取覆盖、模块常量兜底。
"""

from __future__ import annotations

from collections.abc import Callable

from dramaclip.engines.narration import angles, copywriter, scriptwriter, styles, titles
from dramaclip.engines.semantic import conflict, genre


def _get(module: object, name: str) -> Callable[[], str]:
    return lambda: str(getattr(module, name))


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


SPECS: list[PromptSpec] = [
    PromptSpec(
        "prompt.genre_system",
        "题材分类",
        "分析层：判断短剧主导题材（失败自动降级关键词）",
        _get(genre, "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.conflict_system",
        "冲突打分",
        "分析层：逐场景冲突强度评分，驱动选料排序",
        _get(conflict, "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.style_select_system",
        "风格自选",
        "口味层：LLM 读转写从风格库选解说风格",
        _get(styles, "_SELECT_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.angles_system",
        "选题角度",
        "为一模式选出 K 条卖点互异的取材角度",
        _get(angles, "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.scriptwriter_system",
        "剧情解说·结构指令",
        "剧本 JSON 格式与段数/时间轴等结构要求",
        _get(scriptwriter, "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.scriptwriter_fundamentals",
        "剧情解说·基本功层",
        "说书人视角/半句钩/悬念管理等常驻手艺底线",
        _get(scriptwriter, "FUNDAMENTALS"),
    ),
    PromptSpec(
        "prompt.copywriter_system",
        "逐槽填词",
        "六槽位模式（片头/交叉/超短/全片/双人/独白）共用",
        _get(copywriter, "_SYSTEM_PROMPT"),
    ),
    PromptSpec(
        "prompt.titles_system",
        "候选标题",
        "成片详情页 8 条候选标题生成",
        _get(titles, "_SYSTEM_PROMPT"),
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
