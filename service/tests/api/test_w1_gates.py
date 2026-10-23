"""W1·1.5 四门禁的后端侧（G1 降级落点穷举 / G2 判据唯一性）。

G3/G4 的界面侧契约在 desktop vitest（w1Gates.test.ts）。变异锚定：G2 在改前代码上
必红（EXPECT_PLANNER 手抄表真实存在过）；G1 对账表删行即红（穷举面而非点名面）。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_PLAN_DOC = _REPO / "docs" / "superpowers" / "plans" / "2026-10-22-v0.2.3-implementation.md"
_EXPORT_SOURCES = (
    _REPO / "service" / "dramaclip" / "api" / "export.py",
    _REPO / "service" / "dramaclip" / "api" / "export_audit.py",
)


def _degraded_subjects() -> list[str]:
    """从源码**发现**全部 _note_degraded 调用的 subject（含 f-string 前缀）。

    按 2026-10-16 规格 §1.5 门禁 1：不硬编码「10」这个数——调用集合是扫出来的，
    加一处降级而不上对账表即红。
    """
    subjects: list[str] = []
    for path in _EXPORT_SOURCES:
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(r"_note_degraded\(\s*context,\s*(f?)\"([^\"]+)\"", src):
            prefix = match.group(2).split("{")[0]
            subjects.append(prefix)
    return subjects


def test_g1_degradation_sites_covered_by_ledger_manifest() -> None:
    subjects = _degraded_subjects()
    assert len(subjects) >= 8, f"降级调用点扫描异常偏少（{len(subjects)}）：扫描面坏了"
    manifest = _PLAN_DOC.read_text(encoding="utf-8")
    uncovered = [
        subject
        for subject in subjects
        if not any(subject.startswith(prefix) for prefix in _manifest_prefixes(manifest))
    ]
    assert uncovered == [], (
        f"以下降级点不在对账表（规格 §1.2：允许但必须留痕+上屏）：{uncovered}"
    )


def _manifest_prefixes(manifest: str) -> list[str]:
    return re.findall(r"^\| ([^|]+?) \| export_jobs\.degraded_notes \|", manifest, re.M)


def test_g2_judgement_table_is_single_source() -> None:
    """全仓不得出现第二处手抄的「模式 → 来源」字面量表（拦 EXPECT_PLANNER 复发）。"""
    verify_modes = (_REPO / "scripts" / "verify_modes.py").read_text(encoding="utf-8")
    assert "EXPECT_PLANNER" not in verify_modes, "手抄表复活即红"
    plans = (_REPO / "service" / "dramaclip" / "api" / "narration_plans.py").read_text(
        encoding="utf-8"
    )
    assert "def expected_copy_source" in plans, "唯一判定接口失踪"

    # 「模式 → llm_script」的字典字面量只准出现在派生接口所在文件；写入点
    # （copywriter 的 model_copy(update={"planner": ...})）键不是模式名，不误伤
    from dramaclip.api.narration_plans import SUPPORTED_MODES

    key_pattern = re.compile(
        "|".join(
            f"['\"]{mode}['\"]\\s*:\\s*['\"]llm_script['\"]" for mode in sorted(SUPPORTED_MODES)
        )
    )
    offenders: list[Path] = []
    scan_roots = (
        _REPO / "service" / "dramaclip" / "api",
        _REPO / "service" / "dramaclip" / "engines" / "narration",
    )
    for root in scan_roots:
        for path in root.rglob("*.py"):
            if path.name == "narration_plans.py":
                continue
            if key_pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(path)
    assert offenders == [], f"发现第二处「模式 → 来源」手抄表：{offenders}"


def _load_mode_gate():
    script = _REPO / "scripts" / "verify_modes.py"
    spec = importlib.util.spec_from_file_location("verify_modes", script)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    sys.modules["verify_modes"] = gate
    spec.loader.exec_module(gate)
    return gate


def test_g2_mode_gate_tables_derive_from_production_mode_list() -> None:
    """真机门禁的模式表必须由生产清单构造，取值路径上不许留静默默认。

    为什么要在 CI 里钉它：门禁脚本本身不在 CI 跑，手抄表漂了不会有人发现——而漂出去
    那一档过去会按 `many` 的默认预期判绿，报表上就是一条从没被任何判据看过的"绿"。
    变异锚点：把 `ALL_MODES` 改回手抄列表并漏掉一个模式名，本用例必红。
    """
    gate = _load_mode_gate()
    from dramaclip.api.narration_plans import SUPPORTED_MODES

    assert list(gate.ALL_MODES) == list(SUPPORTED_MODES)
    assert set(gate.EXPECT_NARRATION) == set(SUPPORTED_MODES)
    assert gate._mode_table_drift() == []

    # 点名历史上漂过的那档与唯一的手写例外，证明值不是全表落在同一个默认上
    assert gate.EXPECT_NARRATION["highlight_cut"] == "none", "纯剪辑模式被判成了要有旁白"
    assert gate.EXPECT_NARRATION["intro_narration"] == "one", "片头解说只有一段引子旁白"
    assert sorted(m for m, want in gate.EXPECT_NARRATION.items() if want == "none") == [
        "highlight_cut",
        "raw_clip",
        "subtitle_flow",
    ]

