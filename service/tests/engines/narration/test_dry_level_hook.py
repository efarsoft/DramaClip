"""干音电平契约在渲染管线里的收口点：`synthesize_item` 三条出口都得过。

`synthesize_item` 是唯一把干音交给时间轴的地方，三条出口（工作目录已有 / 缓存命中 /
真合成）里只有第三条经过引擎——只钉真合成，历史缓存里那批带外干音就一直不进带。
契约只动工作目录这一份：写回内容寻址缓存等于让同一个键指向两种字节。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dramaclip.engines.narration import synthesis
from dramaclip.engines.tts import level_fix
from dramaclip.infra import compute
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_FFMPEG = resolve_ffmpeg()


@pytest.fixture(scope="module", autouse=True)
def _tmpdir_fixture(tmp_path_factory: pytest.TempPathFactory) -> None:
    global _tmpdir  # noqa: PLW0603 - 模块级缓存目录，供 `_dry` 落临时源
    _tmpdir = str(tmp_path_factory.mktemp("dry-level-src"))


def _render(out: Path, gain_db: float) -> None:
    subprocess.run(  # noqa: S603
        [_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=22050:duration=2",
         "-af", f"volume={gain_db:.2f}dB", "-c:a", "pcm_s16le", str(out)],
        check=True,
    )


def _dry(lufs: float) -> bytes:
    """渲一段**集成响度已知**的干音字节，返回文件内容（indextts2 出厂同格式）。

    先量 0 dB 参考、再按差值加纯增益：写死 `volume=` 的数字会随 lavfi 版本漂，
    用例就会在「素材到底带外没有」这件事上假红。
    """
    out = Path(_tmpdir) / f"dry{abs(lufs):.0f}.wav"
    _render(out, 0.0)
    base_lufs, _ = level_fix.measure_dry_level(out)
    _render(out, lufs - base_lufs)
    return out.read_bytes()


class _Engine:
    """把预置字节写到 out_path，模拟「引擎出厂就在带外」。"""

    name = "kokoro"

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.calls = 0

    def capabilities(self):  # type: ignore[no-untyped-def]
        return type("Caps", (), {"supports_cloning": False})()

    def compute(self):  # type: ignore[no-untyped-def]
        return compute.ComputeReport(
            component="tts.kokoro", requested="cpu", resolved="cpu", actual="cpu",
        )

    def synthesize(self, _text: str, _voice: str, out: Path) -> Path:
        self.calls += 1
        out.write_bytes(self._payload)
        return out


def _pool(engine: _Engine, tmp_path: Path, lines: list[tuple[str, str]]) -> synthesis._EnginePool:
    def log(level: str, msg: str) -> None:
        lines.append((level, msg))

    pool = synthesis._EnginePool("kokoro", tmp_path, log, device="cpu")
    pool._instances = {"kokoro": engine}  # noqa: SLF001 - 测试注入：绕开真模型
    return pool


def _level(path: Path) -> tuple[float, float]:
    return level_fix.measure_dry_level(path)


def _receipt(lines: list[tuple[str, str]], level: str, needle: str) -> list[str]:
    return [msg for msg_level, msg in lines if msg_level == level and needle in msg]


def test_fresh_synth_is_brought_into_contract(tmp_path: Path) -> None:
    """真合成的带外干音：交给时间轴之前已经进带，且这一条有留痕。"""
    lines: list[tuple[str, str]] = []
    pool = _pool(_Engine(_dry(-2.0)), tmp_path, lines)

    target = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")

    lufs, _ = _level(target)
    assert abs(lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB
    assert _receipt(lines, "info", "干音电平契约"), lines


def test_cache_hit_is_brought_in_without_rewriting_the_cache(tmp_path: Path) -> None:
    """缓存命中的旧带外干音同样进带，但缓存原件一个字节不动。

    两条各钉一件事：命中路径也过契约（不然作废旧缓存就等于修好了），
    归一结果不落进内容寻址缓存（键里没有电平这一维）。
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    loud = _dry(-2.0)
    key = synthesis._cache_key("你好", "kokoro", "", "")
    entry = cache / f"{key}.mp3"
    entry.write_bytes(loud)
    lines: list[tuple[str, str]] = []
    engine = _Engine(loud)
    pool = _pool(engine, tmp_path, lines)

    target = pool.synthesize_item("s1", "你好", "", "", tmp_path, cache)

    assert engine.calls == 0, "缓存命中却真推理了，用例测的不是命中路径"
    lufs, _ = _level(target)
    assert abs(lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB
    assert entry.read_bytes() == loud, "归一结果写回了内容寻址缓存"


def test_work_dir_reuse_is_also_brought_in(tmp_path: Path) -> None:
    """工作目录里已有的带外干音（第二次跑同一句）也要进带——出口一漏，重跑就翻车。

    第二次必须**字节不动**：已进带的素材再归一遍就是多一次没人要求的有损重编码。
    """
    loud = _dry(-2.0)
    lines: list[tuple[str, str]] = []
    pool = _pool(_Engine(loud), tmp_path, lines)
    first = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")
    lufs, _ = _level(first)
    assert abs(lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB

    again = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")

    assert again == first
    assert again.read_bytes() == first.read_bytes(), "重跑一次就再归一一遍，世代损失在积累"
    lufs_again, _ = _level(again)
    assert abs(lufs_again - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB


def _probe(tmp_path: Path, payload: bytes) -> tuple[float, float]:
    source = tmp_path / "probe.wav"
    source.write_bytes(payload)
    return level_fix.measure_dry_level(source)


def test_in_band_dry_reaches_the_timeline_byte_identical(tmp_path: Path) -> None:
    """带内的干音不许被管线改写——一次「顺手归一」就是一场没人要求的重编码。"""
    quiet = _dry(-13.0)
    lufs, _ = _probe(tmp_path, quiet)
    assert abs(lufs - level_fix.DRY_LEVEL_TARGET_LUFS) <= level_fix.DRY_LEVEL_TOLERANCE_DB, (
        "素材没造在带内，用例测的不是这条路径"
    )
    lines: list[tuple[str, str]] = []
    pool = _pool(_Engine(quiet), tmp_path, lines)

    target = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")

    assert target.read_bytes() == quiet
    assert _receipt(lines, "info", "未改写"), lines


def test_unmeasurable_dry_warns_and_the_render_continues(tmp_path: Path) -> None:
    """量不到 = warn 上屏 + 原样交付，绝不因为电平判据把整段配音判死。"""
    lines: list[tuple[str, str]] = []
    pool = _pool(_Engine(b"RIFF....not audio"), tmp_path, lines)

    target = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")

    assert target.exists()
    assert _receipt(lines, "warn", "未量到"), lines


def test_a_dry_that_cannot_reach_the_band_is_a_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回执带 note（抬不动/复测没过）= warn——那是一段电平没进带的成品，不是「一切正常」。"""
    monkeypatch.setattr(
        synthesis.level_fix,
        "normalize_dry_level",
        lambda path: level_fix.DryLevelReport(
            path.name, True, -30.0, -0.5, -30.0, -0.5, 0.0, "真峰已到抬升闸，未改写"
        ),
    )
    lines: list[tuple[str, str]] = []
    pool = _pool(_Engine(_dry(-13.0)), tmp_path, lines)

    pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")

    assert _receipt(lines, "warn", "抬升闸"), lines
    assert not _receipt(lines, "info", "电平"), lines
