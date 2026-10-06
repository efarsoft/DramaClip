"""先出语音、再选画面（2026-10-06 业主裁决）：TTS 实测时长到手后整体重铺时间轴。

超短与交叉的编排期窗口只是占位（超短三拍互相重叠、交叉桥段叠在下个场景开头），
实测一到手按模式规则重铺：超短从候选池挑放得下的冲突窗、三拍精确落位；交叉
桥段放进场景间空隙、场景原声窗原样。布局 guessing（预算/前伸/收口）降级为兜底。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    SceneCandidate,
    TimelineSegment,
)


class _StubTts:
    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


def _voice_slots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan: PlanData,
    durations: dict[str, float],
    source_durations: dict[str, float],
) -> PlanData:
    """按槽位给实测时长并跑完整合成+布局。探针键 = 内容寻址文件名首段（槽位前缀）。"""

    def probe(path: Path) -> float:
        return durations[str(Path(path).stem.split("-")[0])]

    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)
    return pipeline.synthesize_narration_texts(
        plan, {"tts.engine": "edge"}, tmp_path, source_durations=source_durations
    )


def _ultra_plan(pool: list[SceneCandidate]) -> PlanData:
    """旧编排形状的超短方案：三拍占位窗互相重叠（布局前的真实形状）。"""
    return PlanData(
        mode="ultra_short_hook",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=68.13, end=68.13,
                audio="narration", narration_id="hook-1",  # type: ignore[arg-type]
            ),
            TimelineSegment(episode_id="ep1", start=68.13, end=72.66, audio="original"),
            TimelineSegment(
                episode_id="ep1", start=72.66, end=76.66,
                audio="narration", narration_id="cta-1",  # type: ignore[arg-type]
            ),
        ],
        narration_texts=[
            NarrationText(id="hook-1", text="钩子文案"),
            NarrationText(id="cta-1", text="点击左下角，免费观看全集。"),
        ],
        scene_pool=pool,
    )


# ---- 超短：候选池按实测时长选景 ----------------------------------------------


def test_ultra_layout_picks_the_first_candidate_that_fits_measured_durations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """钩子实测 20s：第一个候选集尾放不下 CTA，自动落到第二个；三拍精确落位。"""
    plan = _ultra_plan(
        [
            SceneCandidate(episode_id="ep1", start=60.0, end=64.5),  # 64.5+8=72.5 > 70
            SceneCandidate(episode_id="ep1", start=40.0, end=44.5),  # 前 40≥20 ✓ 尾 52.5≤70 ✓
        ]
    )
    result = _voice_slots(
        monkeypatch, tmp_path, plan, {"hook": 20.0, "cta": 8.0}, {"ep1": 70.0}
    )
    assert [(s.start, s.end, s.audio, s.narration_id) for s in result.timeline] == [
        (20.0, 40.0, "narration", "hook-1"),
        (40.0, 44.5, "original", None),
        (44.5, 52.5, "narration", "cta-1"),
    ]


def test_ultra_layout_reports_shortfalls_instead_of_failing_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """全放不下：报错要给出每个候选差多少秒，指引重新生成方案，不静默不出坏片。"""
    plan = _ultra_plan([SceneCandidate(episode_id="ep1", start=60.0, end=64.5)])
    with pytest.raises(RuntimeError, match=r"候选池里没有放得下.*集尾差 2\.5s"):
        _voice_slots(
            monkeypatch, tmp_path, plan, {"hook": 20.0, "cta": 8.0}, {"ep1": 70.0}
        )


def test_ultra_without_pool_falls_back_to_the_patch_ladder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """旧方案没有候选池：走游标修补兜底（前伸/收口），行为与重构前一致。"""
    plan = _ultra_plan([])
    result = _voice_slots(
        monkeypatch, tmp_path, plan, {"hook": 6.0, "cta": 3.0}, {"ep1": 77.07}
    )
    assert [(s.start, s.end, s.audio) for s in result.timeline] == [
        (62.13, 68.13, "narration"),  # 钩子实测 6s：起点前伸，尾锚 68.13
        (68.13, 72.66, "original"),
        (72.66, 75.66, "narration"),
    ]


# ---- 交叉：桥段落进场景间空隙 -------------------------------------------------


def _cross_plan() -> PlanData:
    return PlanData(
        mode="cross_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=10.0, end=18.0, audio="original"),
            TimelineSegment(
                episode_id="ep1", start=40.0, end=44.0,
                audio="narration", narration_id="cross-1",  # type: ignore[arg-type]
            ),
            TimelineSegment(episode_id="ep1", start=40.0, end=47.0, audio="original"),
            TimelineSegment(
                episode_id="ep1", start=60.0, end=64.0,
                audio="narration", narration_id="cross-2",  # type: ignore[arg-type]
            ),
        ],
        narration_texts=[
            NarrationText(id="cross-1", text="承接上一幕"),
            NarrationText(id="cross-2", text="留个缺口"),
        ],
    )


def test_cross_bridges_land_in_the_gaps_between_scenes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """桥段收尾锚在下个场景开头、向前伸进空隙；末段桥接在自己场景窗之后。

    旧布局桥段叠在下个场景开头，IndexTTS 实测一超长就把场景顶出集尾
    （真机 2026-10-06：cross-3 差 0.16s 整条判死）。"""
    plan = _cross_plan()
    result = _voice_slots(
        monkeypatch, tmp_path, plan, {"cross": 6.0}, {"ep1": 90.0}
    )
    assert [(s.start, s.end, s.audio) for s in result.timeline] == [
        (10.0, 18.0, "original"),
        (34.0, 40.0, "narration"),  # 桥1：锚在下个场景 40s 开头，前伸 6s 进空隙
        (40.0, 47.0, "original"),
        (47.0, 53.0, "narration"),  # 末段桥：接在本场景窗后，时长=实测
    ]


def test_cross_bridge_that_does_not_fit_the_gap_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """空隙放不下桥段实测时长：如实报错（不裁音、不重播），不说含糊的越界。"""
    plan = PlanData(
        mode="cross_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=10.0, end=18.0, audio="original"),
            TimelineSegment(
                episode_id="ep1", start=18.0, end=22.0,
                audio="narration", narration_id="cross-1",  # type: ignore[arg-type]
            ),
            TimelineSegment(episode_id="ep1", start=20.0, end=26.0, audio="original"),
        ],
        narration_texts=[NarrationText(id="cross-1", text="承接上一幕")],
    )
    with pytest.raises(RuntimeError, match=r"cross-1 实测 6\.00s.*空隙只有 2\.00s"):
        _voice_slots(monkeypatch, tmp_path, plan, {"cross": 6.0}, {"ep1": 90.0})


def test_cross_bridge_into_another_episode_needs_no_gap_partner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """跨集桥：锚点在 ep2 的场景开头，空隙只看 ep2 自己（集内 0 起算）。"""
    plan = PlanData(
        mode="cross_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=10.0, end=18.0, audio="original"),
            TimelineSegment(
                episode_id="ep2", start=10.0, end=14.0,
                audio="narration", narration_id="cross-1",  # type: ignore[arg-type]
            ),
            TimelineSegment(episode_id="ep2", start=10.0, end=16.0, audio="original"),
        ],
        narration_texts=[NarrationText(id="cross-1", text="承接上一幕")],
    )
    result = _voice_slots(monkeypatch, tmp_path, plan, {"cross": 6.0}, {"ep1": 90.0, "ep2": 40.0})
    assert [(s.episode_id, s.start, s.end, s.audio) for s in result.timeline] == [
        ("ep1", 10.0, 18.0, "original"),
        ("ep2", 4.0, 10.0, "narration"),
        ("ep2", 10.0, 16.0, "original"),
    ]


# ---- 模型兼容 ----------------------------------------------------------------


def test_plan_data_without_scene_pool_validates_empty() -> None:
    """旧库行没有 scene_pool 键：默认空表，布局自动退回游标修补。"""
    raw = PlanData(mode="full_narration").model_dump()
    raw.pop("scene_pool")
    assert PlanData.model_validate(raw).scene_pool == []
