"""把解说文案规则常量导出为 skills/dramaclip-narration 的参考文档。

为什么存在：提示词规则的单一真相源是引擎常量（scriptwriter/titles/llm_prompts），
skill 文档若手写必然漂移（audit 与提示词已漂过一次）。本脚本从常量生成
references/prompt-cards.md；测试以 --check 比对，改动常量后必须重跑导出。

用法：
    uv run python tools/export_skill.py            # 导出到仓库 skills/ 目录
    uv run python tools/export_skill.py --check    # 只比对，不一致退出码 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dramaclip.engines import llm_prompts  # noqa: E402
from dramaclip.engines.narration import scriptwriter, titles  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_TARGET = _REPO / "skills" / "dramaclip-narration" / "references" / "prompt-cards.md"

_HEADER = (
    "<!-- 自动生成：由 service/tools/export_skill.py 从引擎常量导出，勿手改。"
    "改动规则请改 dramaclip/engines/narration/ 源常量后重跑导出。 -->\n\n"
)


def render() -> str:
    specs = "\n".join(
        f"- `{spec.key}`　{spec.title}：{spec.description}" for spec in llm_prompts.SPECS
    )
    genre_rows = "\n".join(
        f"| {genre} | {text} |" for genre, text in scriptwriter.GENRE_EMPHASIS.items()
    )
    parts = [
        _HEADER,
        "# 解说文案规则卡（自动导出）\n",
        "规则文本的权威在引擎常量；本文档是其快照。settings 里对应键的非空覆盖会替换默认值。\n",
        "## 可编辑提示词注册表（settings 键）\n",
        specs,
        "\n## 基本功·通用底座（剧本与填词共用）\n",
        "```text",
        scriptwriter._FUND_BASE.strip(),
        "```\n",
        "## 基本功·全稿版（仅剧本链）\n",
        "```text",
        scriptwriter._FUND_FULL_ONLY.strip(),
        "```\n",
        "## 基本功·逐槽版（仅填词链）\n",
        "```text",
        scriptwriter._FUND_SLOT_ONLY.strip(),
        "```\n",
        "## 题材→表达重点（引导非限制；未知题材不注入）\n",
        "| 题材 | 表达重点 |",
        "|------|----------|",
        genre_rows,
        "",
        "## 候选标题与发布物料（titles 卡，八条六句式+文案+标签）\n",
        "```text",
        titles._SYSTEM_PROMPT.strip(),
        "```",
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只比对不写入，漂移时退出码 1")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not _TARGET.exists():
            print(f"--check 失败：目标不存在 {_TARGET}")
            return 1
        if _TARGET.read_text(encoding="utf-8") != content:
            print(f"--check 失败：{_TARGET} 与引擎常量不一致，请重跑 tools/export_skill.py")
            return 1
        print("prompt-cards.md 与引擎常量一致")
        return 0
    _TARGET.parent.mkdir(parents=True, exist_ok=True)
    _TARGET.write_text(content, encoding="utf-8")
    print(f"已导出 {_TARGET}（{len(content)} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
