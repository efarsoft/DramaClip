"""Phase A→B 交接：拼片清单以 **jobs 逐段验盘**，不再 `glob("seg_*.mp4")` 凑数。

glob 回答「目录里恰好有什么」，不回答「这次渲染产出了什么」。改前的三条静默通路：
某段 ffmpeg 退出码 0 却没落文件（`_finish` 见文件不在就不写 sig，无人报警）、
0 字节残段被当产物、work_dir 里命名撞车的杂项文件被拼进正片。缺一段＝少讲一段剧情，
按规格 §3.3.1 属禁止级降级，当场判死。词法排序把 `seg_1000` 排到 `seg_010` 前面，
顺带一起由清单顺序解决。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _plan(tmp_path: Path, count: int = 2) -> tuple[PlanData, dict[str, str]]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=10.0, audio="original")
            for _ in range(count)
        ],
    )
    return plan, {"ep1": str(source)}


def _export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_cut: Any,
    *,
    count: int = 2,
) -> list[list[Path]]:
    """跑 export_plan，桩掉切割与 concat，返回 `_concat` 实际收到的段清单。"""
    plan, sources = _plan(tmp_path, count)
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(encoder, "_run_cut", fake_cut)
    received: list[list[Path]] = []

    def fake_concat(files: list[Path], target: Path) -> None:
        received.append(list(files))
        Path(target).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", fake_concat)
    encoder.export_plan(
        plan, sources, tmp_path / "out.mp4", tmp_path / "work", parallel=1
    )
    return received


def _write_cut(skip: set[int] = (), empty: set[int] = (), payload: bytes = b"seg") -> Any:
    """按 args[-1] 落产物的假切割；skip/empty 用**段序号**点名要动手脚的段。"""

    def fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        seg = Path(args[-1])
        index = int(seg.stem.split("_")[1])
        if index in skip:
            return  # 模拟 ffmpeg 退出码 0 但没落文件（驱动/会话抽风的产物）
        seg.write_bytes(b"" if index in empty else payload)

    return fake_cut


def test_missing_segment_fails_instead_of_shipping_a_short_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """少一段绝不许悄悄少一段：改前 `_finish` 见文件不在就跳过写 sig，导出照样"成功"。"""
    with pytest.raises(encoder.FilmIntegrityError, match="第 2 段"):
        _export(monkeypatch, tmp_path, _write_cut(skip={1}))


def test_zero_byte_segment_is_not_a_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 字节残留与缺文件同判据：`_read_sig` 早就按"不可复用"处理它，清单侧不许放行。"""
    with pytest.raises(encoder.FilmIntegrityError, match="第 1 段"):
        _export(monkeypatch, tmp_path, _write_cut(empty={0}), count=1)


def test_debris_in_work_dir_never_enters_the_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """work_dir 里撞名 `seg_*.mp4` 的杂项文件不进成片。

    `_prune_stale_segments` 只按 `seg_NNN` 数字尾清理，`seg_handedit.mp4` 这类它不动；
    改前 glob 会把它一起拼进去——用户手放的片段静默变成正片内容。
    """
    work = tmp_path / "work"
    work.mkdir(parents=True)
    (work / "seg_handedit.mp4").write_bytes(b"stray")
    received = _export(monkeypatch, tmp_path, _write_cut())
    assert [seg.name for seg in received[0]] == ["seg_000.mp4", "seg_001.mp4"], (
        f"清单必须恰好等于本次 jobs：{received[0]}"
    )


def test_manifest_orders_by_timeline_index(tmp_path: Path) -> None:
    """拼接顺序＝时间轴序：glob 的词法排序会把 seg_1000 插到 seg_999 前面。"""
    jobs = [
        encoder._SegmentJob(
            index=index, args=[], seg_path=tmp_path / f"seg_{index:03d}.mp4",
            inputs={}, safe_start=0.0, safe_end=0.0, progress_duration=0.05,
            burner_duration=0.0, subtitle_source="none", ass_sha256=None, reuse=True,
        )
        for index in (1000, 0, 999)
    ]
    for job in jobs:
        job.seg_path.write_bytes(b"seg")
    lexical = sorted(job.seg_path for job in jobs)
    assert [p.name for p in lexical] == ["seg_000.mp4", "seg_1000.mp4", "seg_999.mp4"], (
        "对照前提：词法序确实把 1000 插在 999 前面"
    )
    manifest = encoder._concat_manifest(jobs)
    assert [item.path.name for item in manifest] == [
        "seg_000.mp4",
        "seg_999.mp4",
        "seg_1000.mp4",
    ], f"清单必须按时间轴 index 排，且不受入参顺序影响：{manifest}"
    assert [item.index for item in manifest] == [0, 999, 1000], (
        f"序号要跟路径一起交给下游（偏移计算靠它，不靠二次排序）：{manifest}"
    )
