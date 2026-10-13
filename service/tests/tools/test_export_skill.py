"""skills/dramaclip-narration 与引擎常量的漂移守卫。

规则文本的真相源在引擎常量；prompt-cards.md 由 tools/export_skill.py 导出。
有人改了常量却不重跑导出＝skill 在教旧规则（audit/提示词漂移已发生过一次），
这里用 --check 比对拦下。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
_SKILL = _TOOLS.parents[1] / "skills" / "dramaclip-narration"


def test_prompt_cards_match_engine_constants() -> None:
    result = subprocess.run(
        [sys.executable, str(_TOOLS / "export_skill.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "skills/dramaclip-narration/references/prompt-cards.md 与引擎常量不一致："
        f"{result.stdout}{result.stderr}——请运行 uv run python tools/export_skill.py 重新导出"
    )


def test_skill_skeleton_is_complete() -> None:
    """SKILL.md 与研究实证是手写件，构成 skill 的最低骨架；缺件即残废。"""
    assert (_SKILL / "SKILL.md").is_file()
    research = (_SKILL / "references" / "research-findings.md").read_text(encoding="utf-8")
    cards = (_SKILL / "references" / "prompt-cards.md").read_text(encoding="utf-8")
    assert "自动生成" in cards.splitlines()[0], "生成文件头必须有勿手改标记"
    for token in ("六类句式", "14/14", "揭晓", "剧透"):
        assert token in research, f"研究实证缺关键章节：{token}"
