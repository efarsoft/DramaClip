"""Phase C 响度归一：命令构建、测量解析、复核超差即抛。ffmpeg 在此基本不真跑。

例外：`test_film_without_audio_track_raises_operator_message` 用真 ffmpeg 造无音轨成片、
走真 ffprobe——那条路径的判据就是探测结果，替身会把它证明掉。

字符串断言用的 stderr 全部是 `resources/ffmpeg/ffmpeg.exe`（8.1.1-essentials）真跑捕获，
捕获命令写在各夹具注释里。替身只替 `_run`，不替 ffmpeg 的输出格式。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder, loudness
from dramaclip.engines.narration.models import PlanData, StrategySpec, TimelineSegment
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg
from dramaclip.infra.ffmpeg.probe import MediaInfo

_TARGET = loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5)

# 真机捕获，勿手改数字（改一个数字就等于又编一份假夹具）。捕获命令：
#   resources/ffmpeg/ffmpeg.exe -hide_banner -nostats -i <成片> -map 0:a:0 \
#     -af loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json -f null -
# <成片> = data/outputs/86511b3e.../小小球神不好惹_dialogue_narration_fb2006.mp4
#          （Phase C 落地之前的真成片，crest 17.75 dB）。
# 真键名是 output_thresh / target_offset：计划原稿写的 target_thresh / offset 两个都不存在，
# 9 部真成片 + 20 个合成源（含一个静音轨）逐源比对，键集完全一致（见 plan 的 Task 8 实测修正）。
_STDERR = """
[Parsed_loudnorm_0 @ 0000014d608eac40]
{
\t"input_i" : "-27.68",
\t"input_tp" : "-9.93",
\t"input_lra" : "4.10",
\t"input_thresh" : "-37.79",
\t"output_i" : "-15.01",
\t"output_tp" : "-1.50",
\t"output_lra" : "2.80",
\t"output_thresh" : "-25.11",
\t"normalization_type" : "dynamic",
\t"target_offset" : "1.01"
}
[out#0/null @ 0000014d608eae80] video:0KiB audio:24496KiB subtitle:0KiB other streams:0KiB
size=N/A time=00:01:05.75 bitrate=N/A speed=57.3x elapsed=0:00:01.14
"""

# 真机捕获：静音轨（anullsrc）成片的测量块。注意 input_thresh 是真数 -70.00 而非 -inf，
# target_offset 是 "inf"——原先照抄计划的假夹具把这两处都写错了。
_STDERR_SILENT = """
[Parsed_loudnorm_0 @ 0000021ddc507ac0]
{
\t"input_i" : "-inf",
\t"input_tp" : "-inf",
\t"input_lra" : "0.00",
\t"input_thresh" : "-70.00",
\t"output_i" : "-inf",
\t"output_tp" : "-inf",
\t"output_lra" : "0.00",
\t"output_thresh" : "-70.00",
\t"normalization_type" : "dynamic",
\t"target_offset" : "inf"
}
size=N/A time=00:00:12.00 bitrate=N/A speed=18.5x elapsed=0:00:00.64
"""

# ---- ebur128（门禁那套量法）真机捕获 ----
# 捕获命令（与 scripts/verify_modes.py::ebur128 逐字一致）：
#   resources/ffmpeg/ffmpeg.exe -hide_banner -nostats -i <成片> -map 0:a:0 \
#     -af ebur128=peak=true:framelog=quiet -f null -
# <成片> = 小小球神不好惹_full_narration_02bffd.mp4（Phase C 之前，47.1 s，mono 48k）。
# 单位是 dBFS 不是 dBTP：ebur128 的 `peak=true` 打的就是真峰，标签沿用 ffmpeg 自己的措辞。
_EBUR128_ONE = """
[Parsed_ebur128_0 @ 000002c887ff6580] Summary:

  Integrated loudness:
    I:         -14.7 LUFS
    Threshold: -24.7 LUFS

  Loudness range:
    LRA:         2.9 LU
    Threshold: -34.6 LUFS
    LRA low:   -15.7 LUFS
    LRA high:  -12.8 LUFS

  True peak:
    Peak:       -2.5 dBFS
[out#0/null @ 000002c887ff7580] video:0KiB audio:4400KiB subtitle:0KiB
size=N/A time=00:00:47.14 bitrate=N/A speed=385x elapsed=0:00:00.12
"""

# **两块 Summary** 的真机捕获，成因是实测出来的，不是编的：
# <成片> = 小小球神不好惹_ultra_short_hook_2c9b87.mp4（15.2 s）。它的音轨**中途换了声道布局**
# ——ffprobe 逐帧数：前 177 帧 mono（0…3.787687 s），后 533 帧 stereo。于是 ffmpeg 在
# 3.79 s 处打印 `Reconfiguring filter graph because audio parameters changed to
# 48000 Hz, stereo, fltp`，测量滤镜被 flush（打出第一块 Summary），新建的实例量剩下的
# 11.4 s（EOF 时打出第二块）。同一部片子上 loudnorm 也因此吐出**两块 JSON**（见下）。
# 实测：任何 `-af` 都触发（`anull` 也 reconfig=1），`aformat=channel_layouts=stereo` 前置
# 也压不住（依旧 2 块）；把音轨解码成 WAV 再量则 0 reconfig、1 块。
# 所以两块**都不是整片**：第一块是 0…3.79 s（mono，I=-21.4），第二块是 3.79…15.2 s
# （stereo，I=-8.9）；整片解码成 stereo WAV 实测 I=-8.5 / Peak=+0.4，与第二块吻合。
# 门禁的解析器是"后一块覆盖前一块"，因此**取最后一块与门禁同判**（`parse_gate_reading`）。
_EBUR128_TWO = (
    "\n[af#0:0 @ 0000021c76090440] Reconfiguring filter graph because audio "
    "parameters changed to 48000 Hz, stereo, fltp\n"
    """[Parsed_ebur128_0 @ 0000021c76077440] Summary:

  Integrated loudness:
    I:         -21.4 LUFS
    Threshold: -31.4 LUFS

  Loudness range:
    LRA:         0.8 LU
    Threshold: -41.6 LUFS
    LRA low:   -22.1 LUFS
    LRA high:  -21.3 LUFS

  True peak:
    Peak:       -5.4 dBFS
[Parsed_ebur128_0 @ 0000021c76076e00] Summary:

  Integrated loudness:
    I:          -8.9 LUFS
    Threshold: -18.9 LUFS

  Loudness range:
    LRA:         9.6 LU
    Threshold: -28.4 LUFS
    LRA low:   -14.9 LUFS
    LRA high:   -5.3 LUFS

  True peak:
    Peak:        1.9 dBFS
[out#0/null @ 0000021c76078880] video:0KiB audio:1413KiB subtitle:0KiB
size=N/A time=00:00:15.19 bitrate=N/A speed= 236x elapsed=0:00:00.06
"""
)

# 同一部片子（ultra_short_hook_2c9b87）的 loudnorm 测量遍，同样两块。
# 两块的成因与 `_EBUR128_TWO` 完全同一件事。第二块 -9.59/+1.88 与九模式门禁记下的
# "pre-Phase-C input_i=-9.58 / input_tp=+1.88" 对得上；第一块 -21.47/-5.39 是那 3.79 s
# 的 mono 头。`parse_measurements` 原先用 `.search()` 取**第一块**，等于拿片头 3.79 s 的
# 数字去归一整部 15.2 s 的片子——这就是"响度归一后仍偏离目标 3.2 LU"的成因之一。
_STDERR_TWO_BLOCKS = (
    "\n[af#0:0 @ 000001e5dd3fef40] Reconfiguring filter graph because audio "
    "parameters changed to 48000 Hz, stereo, fltp\n"
    """[Parsed_loudnorm_0 @ 000001e5dd3f9340]
{
\t"input_i" : "-21.47",
\t"input_tp" : "-5.39",
\t"input_lra" : "0.00",
\t"input_thresh" : "-31.47",
\t"output_i" : "-13.20",
\t"output_tp" : "-1.50",
\t"output_lra" : "0.00",
\t"output_thresh" : "-23.20",
\t"normalization_type" : "dynamic",
\t"target_offset" : "-0.80"
}
[Parsed_loudnorm_0 @ 000001e5dd3f9000]
{
\t"input_i" : "-9.59",
\t"input_tp" : "1.88",
\t"input_lra" : "8.70",
\t"input_thresh" : "-19.59",
\t"output_i" : "-15.01",
\t"output_tp" : "-3.34",
\t"output_lra" : "7.90",
\t"output_thresh" : "-25.01",
\t"normalization_type" : "dynamic",
\t"target_offset" : "1.01"
}
size=N/A time=00:00:15.22 bitrate=N/A speed=39.2x elapsed=0:00:00.38
"""
)


def _measurement() -> loudness.LoudnessMeasurement:
    return loudness.parse_measurements(_STDERR)


def _rewrapped(stderr: str, *, drop: str) -> str:
    """把真机捕获的块去掉一个键再拼回去，模拟 ffmpeg 改了键名的那一天。"""
    match = loudness._JSON_BLOCK.search(stderr)
    assert match is not None
    block: dict[str, str] = json.loads(match.group(0))
    block.pop(drop)
    return json.dumps(block)


def test_measure_args_target_and_print_format() -> None:
    args = loudness.measure_args("in.mp4", _TARGET)
    joined = " ".join(args)
    assert "loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json" in joined
    assert "-f null" in joined and "-map 0:a:0" in joined


def test_measure_args_never_caps_loglevel() -> None:
    """测量遍不得带 `-loglevel`：loudnorm 的 JSON 打在 AV_LOG_INFO 上。

    真机实测（8.1.1-essentials，同一条命令只换 -loglevel）：
    不带该旗标 → JSON 在；info → 在；warning → 没了；error → 没了。
    四种情况 ffmpeg 都 exit 0，所以少一行旗标不会红，只会让 Phase C 全线量不出响度。
    `normalize_args` 恰恰**要**带 `-loglevel error`——"把两处弄一致"的重构会毁掉整条链。
    """
    assert "-loglevel" not in loudness.measure_args("in.mp4", _TARGET)
    normalize = loudness.normalize_args("in.mp4", "out.mp4", _TARGET, _measurement())
    assert "-loglevel" in normalize and "error" in normalize


def test_parse_measurements() -> None:
    m = _measurement()
    assert (m.integrated_lufs, m.true_peak_dbtp, m.lra) == (-27.68, -9.93, 4.10)
    assert m.threshold == -37.79
    assert m.offset_lu == 1.01, (
        "offset_lu 是 0.0 就说明两遍法的回喂断了（真键名是 target_offset，不是 offset），"
        "不是「这片子本来不需要补偿」——第二遍会二次偏移，实测差到 5.6 LU"
    )


def test_parse_guards_the_keys_ffmpeg_actually_emits() -> None:
    """缺 `target_offset`/`output_thresh` 必须报错，不能 `.get(..., "0")` 悄悄当 0。

    这条比取到什么值更要紧：ffmpeg 哪天改键名，静默 0.0 意味着"响度没归一还照常出片"，
    报错才是"当班的人当天就知道"。`output_thresh` 我们不消费，但一样要守在缺字段里。
    """
    for dropped in ("target_offset", "output_thresh"):
        with pytest.raises(loudness.LoudnessError, match=f"缺字段.*{dropped}"):
            loudness.parse_measurements(_rewrapped(_STDERR, drop=dropped))


def test_parse_missing_block_raises() -> None:
    with pytest.raises(RuntimeError, match="未输出"):
        loudness.parse_measurements("nothing here")


def test_silent_audio_raises() -> None:
    with pytest.raises(RuntimeError, match="无声"):
        loudness.parse_measurements(_STDERR_SILENT)


def test_normalize_args_copies_video_and_resamples() -> None:
    args = loudness.normalize_args("in.mp4", "out.mp4", _TARGET, _measurement())
    joined = " ".join(args)
    assert "-c:v copy" in joined, "视频流必须复制：重编码会让 Phase A 的消重参数白做"
    assert "measured_I=-27.68" in joined and "measured_TP=-9.93" in joined
    assert "offset=1.01" in joined, (
        "第一遍自报的 target_offset 必须回喂进第二遍的滤镜串——这里出现 offset=0.0 就说明"
        "回喂断了（第二遍会二次偏移），不是源不需要补偿"
    )
    assert "linear=true" in joined
    assert "-ar" in args and "48000" in args, "loudnorm 动态模式内部 192k，必须落回 48k"
    assert "-map_metadata" in args and "-1" in args


def test_normalize_args_requests_more_headroom_than_the_gate_allows() -> None:
    """滤镜只要 `target-1.0`，门限只放 `target+0.5`：两者是一对，改一个必须重测过冲。

    loudnorm 在滤镜内部按 192 kHz 限真峰，192k→48k 重采样 + AAC 编码会再抬出采样间过冲，
    门限量的是抬过之后的值。真机实测（14 个滤镜自报 output_tp=-1.50 即被限峰的源）：编码后落在
    −1.50 … −0.64 dBTP，过门的那批里最差只剩 0.08 dB 余量，两个高 crest 源直接超标。
    所以余量必须在滤镜侧先要出来；把门限放宽只是把编码器过冲藏起来。
    """
    joined = " ".join(loudness.normalize_args("in.mp4", "out.mp4", _TARGET, _measurement()))
    filter_tp = _TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB
    assert f"TP={filter_tp}:LRA" in joined
    assert f"TP={_TARGET.true_peak_dbtp}:LRA" not in joined, "归一遍不得按门限值要真峰值"
    assert loudness._TP_ENCODE_HEADROOM_DB == 1.0
    assert loudness._TP_GATE_MARGIN_DB == 0.5
    # 重试那档钉死在 1.5：默认目标 -1.5 下即滤镜 TP=-3.0，是唯一被实测证明可过
    # `intro_narration_325c84`（首遍 -2.5 踩谐振点、编码后 -0.82 dBTP）的档位。
    assert loudness._TP_RETRY_HEADROOM_DB == 1.5
    retry = " ".join(
        loudness.normalize_args(
            "in.mp4",
            "out.mp4",
            _TARGET,
            _measurement(),
            headroom_db=loudness._TP_RETRY_HEADROOM_DB,
        )
    )
    assert f"TP={_TARGET.true_peak_dbtp - 1.5}:LRA" in retry


def test_normalize_args_keeps_192k_audio_bitrate() -> None:
    """`-b:a 192k` 是真峰值门限的一部分，不是可以随手调的码率旋钮。

    真机实测（同一素材、同一滤镜，只把 192k 换 128k）：编码后真峰 -1.40→-0.67、
    -1.35→-0.82、-1.08→-0.15 dBTP——192k 下过门的三条在 128k 下全部超标。
    """
    args = loudness.normalize_args("in.mp4", "out.mp4", _TARGET, _measurement())
    assert args[args.index("-b:a") + 1] == "192k"


def test_target_from_settings_reads_keys() -> None:
    target = loudness.LoudnessTarget.from_settings(
        {"export.loudness_target_lufs": "-12", "export.loudness_true_peak_dbtp": "-1.0"}
    )
    assert (target.integrated_lufs, target.true_peak_dbtp) == (-12.0, -1.0)


def test_target_from_settings_falls_back_to_defaults() -> None:
    """缺失与脏值都回退 DEFAULTS：出片不得因设置表里一格垃圾字符而停摆。"""
    assert loudness.LoudnessTarget.from_settings({}) == _TARGET
    garbage = loudness.LoudnessTarget.from_settings({"export.loudness_target_lufs": "abc"})
    assert garbage.integrated_lufs == -14.0 and garbage.true_peak_dbtp == -1.5


# ---- normalize_in_place 的守卫分支：每条都要"删掉即红"（本批次的规矩） ----


def _measure_stderr(integrated: float, true_peak: float) -> str:
    """替身 loudnorm 测量块：数值是编的，键名必须与真 ffmpeg 一致（见 `_STDERR` 的捕获说明）。"""
    return (
        f'{{"input_i": "{integrated}", "input_tp": "{true_peak}", "input_lra": "8.0",'
        f' "input_thresh": "-30.0", "output_i": "{integrated}", "output_tp": "{true_peak}",'
        f' "output_lra": "8.0", "output_thresh": "-24.0",'
        f' "normalization_type": "dynamic", "target_offset": "0.5"}}'
    )


def _gate_stderr(integrated: float, true_peak: float) -> str:
    """替身 ebur128 Summary：数值是编的，**版式**照 `_EBUR128_ONE`（真机捕获）。

    `LRA low`/`LRA high` 也带 `LUFS` 后缀、`Threshold:` 出现两次（integrated 一次、
    LRA 一次）——解析器要是靠"第一个 Threshold"或"任意 I:"取值，这份替身就能把它照出来。
    """
    return (
        "[Parsed_ebur128_0 @ 000002c887ff6580] Summary:\n\n"
        "  Integrated loudness:\n"
        f"    I:         {integrated} LUFS\n"
        "    Threshold: -24.7 LUFS\n\n"
        "  Loudness range:\n"
        "    LRA:         2.9 LU\n"
        "    Threshold: -34.6 LUFS\n"
        "    LRA low:   -15.7 LUFS\n"
        "    LRA high:  -12.8 LUFS\n\n"
        "  True peak:\n"
        f"    Peak:       {true_peak} dBFS\n"
    )


def _stub_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gates: list[str],
    loudnorms: list[str] | None = None,
    produce_file: bool = True,
    has_audio: bool = True,
) -> list[list[str]]:
    """替身 `_run` + 替身 ffprobe，按**命令形态**分发。

    三条腿：`ebur128` → `gates` 队列（决策遍与复核遍都用门禁那套量法）；
    `loudnorm` + `-f null` → `loudnorms` 队列（两遍法的第一遍）；其余当编码遍，
    写出（或不写出）staged 产物。以前用 `"null" in args` 一条判据就够，是因为量法只有一种；
    现在两种量法都带 `-f null`，只能按滤镜名分。
    """
    pending_loudnorms = list(loudnorms or [])
    seen: list[list[str]] = []
    cursors = {"gate": 0, "loudnorm": 0}
    monkeypatch.setattr(
        loudness.probe,
        "probe",
        lambda _path: MediaInfo(
            duration_s=1.0, width=1080, height=1920, fps=30.0, has_audio=has_audio
        ),
    )

    def fake_run(args: list[str]) -> str:
        seen.append(list(args))
        joined = " ".join(args)
        if "ebur128" in joined:
            out = gates[cursors["gate"]]
            cursors["gate"] += 1
            return out
        if "loudnorm" in joined and "null" in args:
            out = pending_loudnorms[cursors["loudnorm"]]
            cursors["loudnorm"] += 1
            return out
        if produce_file:  # 编码遍：写出 staged 产物
            Path(args[-1]).write_bytes(b"normalized")
        return ""

    monkeypatch.setattr(loudness, "_run", fake_run)
    return seen


def _encodes(seen: list[list[str]]) -> list[list[str]]:
    """编码遍 = 不带 `-f null` 的那些调用（两种量法都带 null，编码器不带）。"""
    return [call for call in seen if "null" not in call]


def test_normalize_in_place_replaces_file_and_returns_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """顺路径：staged 产物原地替换成片，返回的必须是归一后那次复核实测。

    源读数 -23.7 LUFS / -3.1 dBTP → 纯增益要 +9.7 dB，真峰被抬到 +6.6，远超滤镜要的
    -2.5，所以这条走的是 loudnorm 路：**四次** `_run`（ebur128 决策遍 + loudnorm 测量遍
    + 编码遍 + ebur128 复核遍）。
    """
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-23.7, -3.1), _gate_stderr(-14.1, -2.0)],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.integrated_lufs == -14.1, "返回的必须是复核（第二遍）实测，不是归一前的"
    assert film.read_bytes() == b"normalized", "成片必须被归一产物原地替换"
    assert len(seen) == 4, "决策遍 + loudnorm 测量遍 + 编码遍 + 复核遍，缺一不可"
    assert len(_encodes(seen)) == 1, "只编一次"


def test_recheck_measures_the_staged_file_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复核必须量 staged 产物：先 replace 再量，超标的那一版就已经坐在成品路径上了。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-23.7, -3.1), _gate_stderr(-14.1, -2.0)],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    recheck_input = seen[-1][seen[-1].index("-i") + 1]
    # 名字从 loudnorm_stage.mp4 改成 loudness_stage.mp4：现在这里躺着的可能是增益路的产物，
    # 叫 loudnorm 就是名字说谎（与 _MIX_PEAK_CEILING_DBFS 改名同一个理由）。
    assert Path(recheck_input).name == "loudness_stage.mp4"
    assert "ebur128" in " ".join(seen[-1]), "复核必须用门禁那套量法（ebur128），不是 loudnorm 自报"


def test_recheck_drift_beyond_tolerance_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复核是 Phase C 的验收线：归一后仍偏离目标超容差必须抛，不得放行。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-23.7, -3.1), _gate_stderr(-20.0, -3.0)],  # 复核差 6 LU
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    with pytest.raises(loudness.LoudnessError, match="偏离目标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert film.read_bytes() == b"film", (
        "复核没过就不许碰成品路径：库里写着 failed、磁盘上却躺着一版能播的超标片，"
        "是最难查的那种不一致"
    )


def test_recheck_true_peak_over_limit_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真峰超门限且重试仍超 → 抛错。staged 复核不过就不许碰成品路径。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-23.7, -3.1),
            _gate_stderr(-14.0, -0.4),  # 真峰超 -1.5+0.5
            _gate_stderr(-14.0, -0.4),  # 重试后仍超
        ],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len(_encodes(seen)) == 2, "抛错前恰好重试过一次"
    assert film.read_bytes() == b"film", "同上：超标片不得留在成品路径"


def test_recheck_true_peak_at_exact_gate_margin_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """门限余量钉死在 +0.5：正好压线算过，超一丝算不过。

    这 0.5 dB 是给 AAC/重采样过冲留的预算，不是可以随手放宽的容错；真要动它得先动
    `_TP_ENCODE_HEADROOM_DB` 并重测过冲（见那条用例）。
    """
    for true_peak, expect_pass in ((-1.0, True), (-0.99, False)):
        case = tmp_path / f"case_{abs(true_peak)}"
        case.mkdir()
        film = case / "final.mp4"
        film.write_bytes(b"film")
        _stub_run(
            monkeypatch,
            gates=[
                _gate_stderr(-23.7, -3.1),
                _gate_stderr(-14.0, true_peak),
                # 超线的那一格会触发有界重试：重试复核也喂同一个超标值，让它走到抛错。
                _gate_stderr(-14.0, true_peak),
            ],
            loudnorms=[_measure_stderr(-23.7, -3.1)],
        )
        if expect_pass:
            loudness.normalize_in_place(film, target=_TARGET, work_dir=case / "wn")
            assert film.read_bytes() == b"normalized", "正好压在 target+0.5 上应当放行"
        else:
            with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
                loudness.normalize_in_place(film, target=_TARGET, work_dir=case / "wn")
            assert film.read_bytes() == b"film"


# ---- 真峰值复核失败的有界重试（过冲对所请求 TP 不单调，一次尝试可能冤枉好片） ----
#
# 实测依据（plan 的 Task 8 实测修正）：同一部 `intro_narration` 真成片按滤镜 TP
# −1.5/−2.0/−2.25/−2.5/−2.75/−3.0/−3.5 逐个重编，过冲 0.12/0.96/0.87/**1.68**/0.99/0.71/0.66 dB
# ——−2.5（= 默认目标 −1.5 减 1.0 dB 余量）正踩谐振点，而 −3.0（减 1.5 dB）可过、
# integrated 偏离仅 0.06 LU。所以重试是**换余量重编一次**，不是循环到成功为止。


def test_true_peak_recheck_retries_once_with_more_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """真峰复核超标 → 从**原始成片**按 `_TP_RETRY_HEADROOM_DB` 重编一次，过了就落地。

    重试不回炉测量遍：源没变，第一遍的 measured_* 仍然有效；变的只有滤镜 TP。
    """
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-23.7, -3.1),  # 源读数（决策遍，门禁量法）
            _gate_stderr(-14.0, -0.4),  # 复核 1：超门限（-1.5 + 0.5 = -1.0）
            _gate_stderr(-14.0, -1.4),  # 复核 2（重试产物）：过门
        ],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.true_peak_dbtp == -1.4, "返回的必须是重试那一版的复核"
    assert film.read_bytes() == b"normalized"
    encodes = _encodes(seen)
    assert len(encodes) == 2, "一次重试：两遍编码，不多不少"
    first, second = (" ".join(call) for call in encodes)
    assert f"TP={_TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB}" in first
    assert f"TP={_TARGET.true_peak_dbtp - loudness._TP_RETRY_HEADROOM_DB}" in second, (
        "重试必须真的换更大的余量（实测可过的那一档是滤镜 TP=-3.0）"
    )
    assert encodes[1][encodes[1].index("-i") + 1] == str(film), (
        "重试从原始成片重编，不许拿上一遍的 staged 产物再压一次（那是第三次有损代）"
    )
    assert "重试" in caplog.text, "哪一版过的门必须留痕：队列页/Task 9 要能区分一次过与重试过"


def test_true_peak_retry_is_bounded_and_still_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重试也超标 → 抛错，成品路径不动。不许循环到成功为止：打不到的目标就该响。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-23.7, -3.1),
            _gate_stderr(-14.0, -0.4),  # 复核 1 超标
            _gate_stderr(-14.0, -0.6),  # 复核 2 仍超标
        ],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    encodes = _encodes(seen)
    assert len(encodes) == 2, "只有一次重试；第三次编码出现即说明循环没界"
    assert film.read_bytes() == b"film"


def test_drift_failure_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integrated 偏离超容差 → 立即抛，不重试：那是电平问题，多要余量救不了，重试只会掩盖真缺陷。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-23.7, -3.1), _gate_stderr(-20.0, -3.0)],  # 复核差 6 LU
        loudnorms=[_measure_stderr(-23.7, -3.1)],
    )
    with pytest.raises(loudness.LoudnessError, match="偏离目标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len(seen) == 4, "决策+loudnorm 测量+编码+复核各一次；第五次调用出现即说明漂移也走了重试"
    assert len(_encodes(seen)) == 1
    assert film.read_bytes() == b"film"


def test_normalize_without_output_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-23.7, -3.1)],
        loudnorms=[_measure_stderr(-23.7, -3.1)],
        produce_file=False,
    )
    with pytest.raises(loudness.LoudnessError, match="未产出文件"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")


def test_film_without_audio_track_raises_operator_message(
    repo_root: Path, tmp_path: Path
) -> None:
    """无音轨成片必须说人话（真 ffmpeg 造片 + 真 ffprobe 探测，不替身）。

    可达路径：`cut_segment_args` 的 else 分支把音频写成可选映射（`-map 0:a:0?`），
    无音轨的源集就会产出无音轨的段，concat 之后是无音轨的成片。
    真机实测修复前的报错是 `ffmpeg 退出码 4294967274：… Stream map '' matches no streams`
    （4294967274 是 -22 的无符号回绕）——运维看不懂，也看不出该怎么办。
    顺带记一条行为变更：Phase C 之前无音轨成片是**静默交付**的，现在硬失败；
    这符合降级分类表（近乎无声的片子不该交付），但它是一处行为变更。
    """
    film = tmp_path / "video_only.mp4"
    subprocess.run(  # noqa: S603
        [
            loudness.resolve_ffmpeg(),
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
            "-c:v", "libx264", "-preset", "ultrafast", "-an",
            str(film),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    before = film.read_bytes()
    with pytest.raises(loudness.LoudnessError, match="没有音轨"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert film.read_bytes() == before, "无音轨是事前判定的失败，不该留下半截产物"


def test_parse_missing_field_raises() -> None:
    with pytest.raises(loudness.LoudnessError, match="缺字段"):
        loudness.parse_measurements('{"input_i": "-23.7"}')


def test_parse_garbage_number_raises() -> None:
    with pytest.raises(loudness.LoudnessError, match="无法解析"):
        loudness.parse_measurements(
            '{"input_i": "abc", "input_tp": "-3.0", "input_lra": "8.0",'
            ' "input_thresh": "-30.0", "output_thresh": "-24.0", "target_offset": "0.5"}'
        )


def test_run_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loudness, "resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        loudness.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"),
    )
    with pytest.raises(loudness.LoudnessError, match="退出码 1"):
        loudness._run([])


# ---- 门禁量法（ebur128）+ "纯增益优先"的分支选择 ----
#
# 为什么换量法：门禁用 `ebur128=peak=true` 判红绿，Phase C 原先却拿 loudnorm 自报的
# `input_i` 决策与复核。两套实现同一部片子实测差 0.2 LU（门禁注释里记着），更要命的是
# **音轨中途换声道布局时 loudnorm 会吐两块 JSON**（成因见 `_EBUR128_TWO` 的注释），
# 而 `.search()` 取第一块——`ultra_short_hook_2c9b87` 的前 3.79 s mono 头，
# I=-21.47/TP=-5.39，拿它去归一整部 15.2 s 的片子，复核自然"偏离目标 3.2 LU"。


def test_measure_gate_args_is_the_gate_command() -> None:
    """决策遍/复核遍必须与 `scripts/verify_modes.py::ebur128` 是同一条命令。

    Phase C 的验收线就是门禁那条断言；两边量法不一致的话，"Phase C 说过了、门禁说没过"
    这种扯皮会一直有（本批次实测差 0.2 LU，而门禁窗口只比生产容差松 0.5）。
    """
    joined = " ".join(loudness.measure_gate_args("in.mp4"))
    assert "-af ebur128=peak=true:framelog=quiet" in joined
    assert "-map 0:a:0" in joined and "-f null" in joined
    assert "-hide_banner" in joined and "-nostats" in joined


def test_measure_gate_args_never_caps_loglevel() -> None:
    """ebur128 的 Summary 也打在 AV_LOG_INFO 上，与 loudnorm 同一个坑。

    真机实测（8.1.1-essentials，同一条命令只换 -loglevel，片子 full_narration_02bffd）：
    不带该旗标 → 1 块 Summary；info → 1 块；warning → **0 块**；error → **0 块**；
    四种情况 ffmpeg 都 exit 0。少这一行旗标不会红，只会让 Phase C 量不出响度。
    """
    assert "-loglevel" not in loudness.measure_gate_args("in.mp4")


def test_parse_gate_reading_single_summary() -> None:
    r = loudness.parse_gate_reading(_EBUR128_ONE)
    assert (r.integrated_lufs, r.true_peak_dbtp) == (-14.7, -2.5)
    assert (r.lra, r.threshold) == (2.9, -24.7), (
        "Threshold 在 Summary 里出现两次（integrated 一次、Loudness range 一次），"
        "取错那一节就会把 -34.6 当成门限阈值"
    )


def test_parse_gate_reading_takes_the_last_summary() -> None:
    """两块 Summary 时取**最后一块**——与门禁的解析器同判（它是"后一块覆盖前一块"）。

    真机捕获 `_EBUR128_TWO`（ultra_short_hook_2c9b87，音轨 3.79 s 处 mono→stereo）：
    第一块 I=-21.4/Peak=-5.4 是片头 3.79 s，第二块 I=-8.9/Peak=+1.9 是剩下 11.4 s。
    两块都不是整片（整片解码成 stereo WAV 实测 I=-8.5/Peak=+0.4，与第二块吻合），
    但门禁读的是第二块，Phase C 就必须读第二块，否则两边判的不是同一段音频。
    """
    r = loudness.parse_gate_reading(_EBUR128_TWO)
    assert (r.integrated_lufs, r.true_peak_dbtp) == (-8.9, 1.9)


def test_parse_gate_reading_missing_summary_raises() -> None:
    with pytest.raises(loudness.LoudnessError, match="ebur128"):
        loudness.parse_gate_reading("nothing here")
    with pytest.raises(loudness.LoudnessError, match="ebur128"):
        loudness.parse_gate_reading(
            "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n"
            "    I:         -14.7 LUFS\n"  # 少了 True peak 那节
        )


def test_parse_measurements_takes_the_last_json_block() -> None:
    """loudnorm 的两遍法回喂也必须用**最后一块**，理由同上（真机捕获 `_STDERR_TWO_BLOCKS`）。

    第一块 -21.47/-5.39/LRA 0.00 是片头 3.79 s 的 mono 头；第二块 -9.59/+1.88/LRA 8.70
    才是剩下的 11.4 s。原先 `.search()` 取第一块，等于拿片头去归一整部片子。
    """
    m = loudness.parse_measurements(_STDERR_TWO_BLOCKS)
    assert (m.integrated_lufs, m.true_peak_dbtp) == (-9.59, 1.88)
    assert (m.lra, m.offset_lu) == (8.70, 1.01)
    assert len(loudness._JSON_BLOCK.findall(_STDERR_TWO_BLOCKS)) == 2, (
        "夹具必须真的是两块：只有一块的话这条用例证明不了'取最后一块'"
    )


def _gain_fits(integrated: float, true_peak: float) -> bool:
    """决策规则的复算（测试侧独立写一遍，避免"照着实现抄断言"）。"""
    gain = _TARGET.integrated_lufs - integrated
    ask = _TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB
    return true_peak + gain <= ask


# 留痕断言必须钉**整句前缀**，不能只匹配 "gain" / "loudnorm" 这种子串。
# 变异检验实测出来的：那行 info 里同时还印着 `gain=+6.50 dB` 这个字段，所以走 loudnorm 路时
# `"gain" in caplog.text` **照样为真**——把判据改成恒假（增益路永不触发）之后，
# 只匹配子串的真 ffmpeg 用例照绿，等于没守。改成整句前缀之后同一条变异立刻红。
_LOG_GAIN = "响度归一走 gain 路"
_LOG_LOUDNORM = "响度归一走 loudnorm 路"
_LOG_FALLBACK = "退回 loudnorm 路"


def test_gain_branch_chosen_when_pure_gain_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """纯增益够得着目标又碰不到真峰 → 走 `volume=` + 限幅，**完全不碰 loudnorm**。

    源读数 -20.0 LUFS / -12.0 dBTP：gain=+6.0 dB（把片子抬到目标 -14.0），
    加完真峰 -6.0，仍低于滤镜要的 -2.5，所以不需要动态压缩。
    为什么优先它：loudnorm 的 dynamic 模式在短素材上不收敛
    （15.2 s 的真成片实测残差 3.2 LU），而纯增益是确定性的、不泵动。
    """
    assert _gain_fits(-20.0, -12.0), "用例前提：这组读数必须落在增益路"
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-20.0, -12.0), _gate_stderr(-14.0, -6.0)],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.integrated_lufs == -14.0
    assert film.read_bytes() == b"normalized"
    encodes = _encodes(seen)
    assert len(encodes) == 1 and len(seen) == 3, "决策遍 + 编码遍 + 复核遍，不该有 loudnorm 测量遍"
    joined = " ".join(encodes[0])
    assert "volume=6.0000dB" in joined, "增益必须正好是 target_I - measured_I"
    assert not any("loudnorm=" in " ".join(call) for call in seen), (
        "走了增益路就不该出现 loudnorm 滤镜：决策只认 ebur128 的读数"
    )
    assert _LOG_GAIN in caplog.text, "走了哪条路必须留痕（与真峰重试那行 info 同一个规矩）"


def test_gain_branch_safety_net_is_the_same_lookahead_limiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """增益路后面那道限幅是**安全网**，天花板取滤镜侧真峰余量，且必须 `level=disabled`。

    `level=disabled` 不是洁癖：alimiter 默认 `level=true` 会按 1/limit 把输出抬回去
    （自动电平），那就把 Task 7 刚消灭的归一化从后门放回来了——真机实测 0 dBFS 正弦过
    `limit=0.7079`：默认参数 max_volume 0.0 dB，disabled 才是 -3.0 dB。
    limit 取 `target_TP - _TP_ENCODE_HEADROOM_DB` = -2.5 dBTP → 线性 0.7499。
    """
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-20.0, -12.0), _gate_stderr(-14.0, -18.0)],
    )
    loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    joined = " ".join(_encodes(seen)[0])
    ask = _TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB
    want = f"alimiter=limit={10 ** (ask / 20):.4f}:level=disabled:latency=true"
    assert want in joined
    assert joined.index("volume=") < joined.index("alimiter="), (
        "先增益后限幅；反过来等于限了个别的信号"
    )
    # 编码外壳与 loudnorm 路同一套：视频流复制、192k、落回 48k、擦元数据
    assert "-c:v copy" in joined and "-b:a 192k" in joined
    assert "-ar 48000" in joined and "-map_metadata -1" in joined


def test_gain_branch_decision_uses_the_filter_ask_not_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判据必须是**滤镜侧要的** `target_TP − 1.0 = −2.5`，不是复核门限 `target_TP + 0.5 = −1.0`。

    两个数差 1.5 dB，正好是 AAC/重采样过冲的预算（见 `_TP_ENCODE_HEADROOM_DB` 的实测）。
    拿门限当判据的话，预测真峰落在 (−2.5, −1.0] 这一带的素材会被判成"增益够用"，
    编出来再过冲 0.6–1.7 dB 就顶穿门限——本用例钉的就是这一带：
    源 −16.0 LUFS / −4.0 dBTP，gain=+2.0 dB，预测真峰 **−2.0**，
    高于滤镜要的 −2.5（必须走 loudnorm），却低于门限 −1.0（用错判据就会走增益）。
    """
    predicted = -4.0 + (_TARGET.integrated_lufs - -16.0)
    ask = _TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB
    gate = _TARGET.true_peak_dbtp + loudness._TP_GATE_MARGIN_DB
    assert predicted == -2.0 and ask < predicted <= gate, "用例前提：这组读数必须落在两个数之间"
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-16.0, -4.0), _gate_stderr(-14.0, -2.6)],
        loudnorms=[_measure_stderr(-16.0, -4.0)],
    )
    loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    joined = " ".join(_encodes(seen)[0])
    assert "loudnorm=" in joined and "volume=" not in joined, (
        f"预测真峰 {predicted} 高于滤镜要的 {ask}，必须走 loudnorm 路（门限 {gate} 不是判据）"
    )


def test_loudnorm_branch_when_gain_would_break_true_peak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """纯增益会把真峰顶穿 → 素材是真需要动态压缩，保留原两遍 loudnorm 路。

    用的就是 `intro_narration_c3eb30` 的真机读数：-9.8 LUFS / +3.38 dBTP。
    gain=-4.2 dB 之后真峰还有 -0.8，高于滤镜要的 -2.5（也高于门限 -1.0），
    crest 13.2 dB > 11.5 dB，正是 loudnorm 自己也会退回 dynamic 的那一档。
    """
    assert not _gain_fits(-9.8, 3.38), "用例前提：这组读数必须落在 loudnorm 路"
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[_gate_stderr(-9.8, 3.38), _gate_stderr(-14.0, -2.0)],
        loudnorms=[_measure_stderr(-9.69, 3.38)],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    joined = " ".join(_encodes(seen)[0])
    assert "loudnorm" in joined and "volume=" not in joined
    assert "measured_I=-9.69" in joined, "两遍法的回喂还在（读数来自 loudnorm 自己的测量遍）"
    assert len(seen) == 4, "增益路省掉的那一遍 loudnorm 测量，这条路必须补上"
    assert _LOG_LOUDNORM in caplog.text and _LOG_GAIN not in caplog.text


def test_gain_branch_falls_back_to_loudnorm_when_recheck_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """增益路的预测**可能不准** → 复核不过就退回 loudnorm 路一次，两条都不过才抛。

    为什么必须有这条退路（真机实测，ultra_short_hook_2c9b87）：按第二块读数
    I=-8.9/TP=+1.9 算，gain=-5.1 dB 后真峰"应该"是 -3.2，实际编出来是 **-1.4 dBTP**
    ——差了 1.8 dB，比 `_TP_ENCODE_HEADROOM_DB`(1.0) 与门限余量(0.5) 加起来还多。
    原因是那两块读数各只覆盖片子的一段（见 `_EBUR128_TWO`），而重编之后音轨变均匀、
    复核量的是整片。预测失准就直接硬失败的话，七部本来就过的模式会凭空多一种死法。
    """
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-20.0, -12.0),  # 源读数：增益路
            _gate_stderr(-14.0, -0.4),   # 增益产物复核：真峰超门限 -1.0
            _gate_stderr(-14.0, -1.4),   # loudnorm 产物复核：过门
        ],
        loudnorms=[_measure_stderr(-20.0, -12.0)],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    encodes = _encodes(seen)
    assert len(encodes) == 2, "增益一遍 + loudnorm 一遍；第三次编码出现即说明退路没界"
    assert "volume=" in " ".join(encodes[0]) and "loudnorm" in " ".join(encodes[1])
    assert encodes[1][encodes[1].index("-i") + 1] == str(film), (
        "退路必须从**原始成片**重编，不许拿增益产物再压一次（那是白送一次有损代）"
    )
    assert checked.true_peak_dbtp == -1.4
    assert film.read_bytes() == b"normalized"
    assert _LOG_GAIN in caplog.text and _LOG_FALLBACK in caplog.text, "换路必须留痕"


def test_gain_branch_falls_back_when_recheck_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """增益路复核**响度**没打到（不只是真峰）也要退回 loudnorm 路。

    这正是 `ultra_short_hook_2c9b87` 原来那种死法的形状：复核偏离目标 3.2 LU
    （实测 -17.2 / 目标 -14.0）。增益是算术、照理不会偏，但决策读数可能只覆盖片子的一段
    （音轨中途换声道布局，见 `parse_gate_reading`），重编之后音轨变均匀、复核量的是整片，
    预测就会失准。偏了不许直接放行，也不许直接判死，退回 loudnorm 路再试一次。
    """
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-20.0, -12.0),  # 源读数：增益路
            _gate_stderr(-17.2, -12.0),  # 增益产物复核：偏离 3.2 LU，超容差 2.0
            _gate_stderr(-14.0, -2.0),   # loudnorm 产物复核：过门
        ],
        loudnorms=[_measure_stderr(-20.0, -12.0)],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len(_encodes(seen)) == 2, "增益一遍 + loudnorm 一遍"
    assert checked.integrated_lufs == -14.0
    assert film.read_bytes() == b"normalized"
    assert _LOG_FALLBACK in caplog.text and "偏离" in caplog.text, (
        "响度没打到就退路，这件事必须留痕"
    )


def test_gain_branch_fallback_still_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两条路都打不到规格 → 抛。退路不是"总能出片"的兜底。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        gates=[
            _gate_stderr(-20.0, -12.0),
            _gate_stderr(-14.0, -0.4),  # 增益产物：真峰超
            _gate_stderr(-14.0, -0.6),  # loudnorm 产物：仍超
            _gate_stderr(-14.0, -0.6),  # loudnorm 有界重试产物：仍超
        ],
        loudnorms=[_measure_stderr(-20.0, -12.0)],
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len(_encodes(seen)) == 3, "增益 1 遍 + loudnorm 首遍 + loudnorm 重试 1 遍，到此为止"
    assert film.read_bytes() == b"film", "成品路径不许留下超标片"


def test_gain_branch_does_not_loosen_the_budgets() -> None:
    """两个预算数不许因为多了增益路就被顺手放宽（门禁失败文案里写着不许，owner 也认了）。"""
    assert loudness._TOLERANCE_LU == 2.0
    assert loudness._TP_GATE_MARGIN_DB == 0.5
    assert loudness._TP_ENCODE_HEADROOM_DB == 1.0


def test_filter_true_peak_ask_is_one_number_in_all_three_places() -> None:
    """滤镜侧真峰天花板只有一个来源：loudnorm 的 TP、alimiter 的 limit、增益路的判据。

    判据说的是"加完增益真峰落在 X 以内，所以不用压缩"；安全网就必须真的钉在同一个 X 上。
    三处各写一遍 `target.true_peak_dbtp - _TP_ENCODE_HEADROOM_DB` 的话，改一处忘两处 →
    判据批准的东西没人执行，要等复核才发现，而复核不过的代价是整片重编甚至整条导出失败。
    """
    ask = loudness.filter_true_peak_ask(_TARGET)
    assert ask == _TARGET.true_peak_dbtp - loudness._TP_ENCODE_HEADROOM_DB == -2.5

    gain_args = " ".join(loudness.gain_normalize_args("in.mp4", "out.mp4", _TARGET, 6.0))
    assert f"alimiter=limit={10 ** (ask / 20):.4f}" in gain_args, (
        "安全网的天花板必须就是判据用的那个数（-2.5 dBTP → 线性 0.7499）"
    )
    norm_args = " ".join(
        loudness.normalize_args("in.mp4", "out.mp4", _TARGET, _measurement())
    )
    assert f"TP={ask}:LRA" in norm_args, "loudnorm 路首遍也按同一个数要真峰"
    assert (
        loudness.filter_true_peak_ask(_TARGET, loudness._TP_RETRY_HEADROOM_DB) == -3.0
    ), "重试那一档只是换个 headroom 传进来，不许另算一套"


def _real_gate(ffmpeg: str, path: Path) -> tuple[float, float]:
    """用门禁那条命令量真产物，返回 (integrated LUFS, true peak dBTP)。"""
    proc = subprocess.run(  # noqa: S603
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
         "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    r = loudness.parse_gate_reading(proc.stderr)
    return r.integrated_lufs, r.true_peak_dbtp


# 两条真 ffmpeg 用例共用的确定性原声床（不含随机种子：`anoisesrc` 在 8.1.1 上没有 seed
# 选项、同一条命令连跑三次真峰会漂，理由与实测见 test_mix 的 `_BED_EXPR`）。
_BED = (
    "aevalsrc=0.35*sin(2*PI*97*t)+0.3*sin(2*PI*613*t)"
    "+0.2*sin(2*PI*2371*t)+0.15*sin(2*PI*5903*t):s=48000:d={dur}"
)


def _build_film(ffmpeg: str, out: Path, dur: str, audio_chain: str) -> None:
    """造一部"Phase C 之前"形状的成片：testsrc 视频 + 床音、AAC 128k、48 kHz。"""
    subprocess.run(  # noqa: S603
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={dur}",
         "-f", "lavfi", "-i", _BED.format(dur=dur),
         "-filter_complex", f"[1:a]{audio_chain}[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(out)],
        check=True, capture_output=True, timeout=300,
    )


def test_gain_branch_hits_the_target_on_real_audio(
    repo_root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """真 ffmpeg 端到端：一部 **15.2 s** 的偏低真成片，跑真 `normalize_in_place`，门禁量法验收。

    时长是这条用例的一半意义：九模式门禁失败的正是 15.2 s 的 `ultra_short_hook`，
    loudnorm 的 dynamic 模式在这么短的素材上不收敛（实测残差 3.2 LU）。所以断言不止
    "落在窗口里"，而是**几乎正中目标**——纯增益是算术，长度不参与。

    素材是四正弦床衰减 12 dB，crest 8.9 dB < 11.5 dB，判据必然落在增益路。
    验收用的是 `scripts/verify_modes.py::ebur128` 那条命令与那个窗口
    （目标 -14.0 ± 2.5 LU、真峰 ≤ -1.0 dBTP）。

    `volume=-12.0dB` 的 **dB 后缀不可省**：真机实测去掉后缀（`volume=-12.0`）时 ffmpeg 把它
    当**线性增益因子**读，-12 倍即 +21.6 dB 反相放大，同一张床出来是 `I=-8.4 LUFS /
    Peak=+21.0 dBFS`（128k 编码把它削回来了，否则更高）——衰减变成了猛推。

    真机实测（8.1.1-essentials，连跑两次逐位相同）：归一前 `I=-20.50 LUFS / Peak=-11.60 dBFS`，
    gain=+6.50 dB，归一后 **`I=-14.00 LUFS / Peak=-4.80 dBFS`，偏离 0.00 LU**。

    最后两条断言是一对**声学**守卫，缺一就抓不住"安全网在偷偷归一"。真机实测把 alimiter 的
    `level=disabled` 删掉（`level` 回到默认 true，即自动电平）：增益产物被凭空抬 **+2.5 dB**
    （1/0.7499）到 `I=-11.50 LUFS`，偏离 2.50 LU 超容差 → 复核驳回 → 退回 loudnorm 路重编，
    **最终产物照样是 -14.00**。所以只量最终响度的断言看不见它（复核 + 退路把它掩盖了，
    代价是每部片子白编一遍、而且增益路等于废掉）——必须同时断言"**没走退路**"才会红。
    """
    ffmpeg = resolve_ffmpeg()
    film = tmp_path / "quiet_film.mp4"
    _build_film(ffmpeg, film, "15.2", "aformat=sample_fmts=fltp,volume=-12.0dB")

    before_i, before_tp = _real_gate(ffmpeg, film)
    assert before_i < _TARGET.integrated_lufs - 2.5, (
        f"素材必须真的偏出窗口（实测 {before_i:.2f} LUFS），否则这条用例证明不了什么"
    )
    assert _gain_fits(before_i, before_tp), "素材 crest 太大就会走 loudnorm 路，该换素材"

    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    after_i, after_tp = _real_gate(ffmpeg, film)
    assert _LOG_GAIN in caplog.text, (
        "15.2 s 的偏低片子必须走增益路；只匹配 'gain' 子串会被同一行里的 gain=+6.50 dB 骗过"
    )
    assert _LOG_FALLBACK not in caplog.text, (
        "增益路必须自己打到目标，走退路就说明这一遍白编了"
        "（实测：删掉 alimiter 的 level=disabled 就会走到这里）"
    )
    assert after_i == pytest.approx(_TARGET.integrated_lufs, abs=0.5), (
        f"增益路是确定性的，15.2 s 实测偏离 0.00 LU；这次 {after_i:.2f} LUFS"
        f"（目标 {_TARGET.integrated_lufs:.1f}）。偏离到 2.0 LU 以上说明限幅器在自动电平"
    )
    assert abs(after_i - _TARGET.integrated_lufs) <= loudness._TOLERANCE_LU
    assert after_tp <= _TARGET.true_peak_dbtp + loudness._TP_GATE_MARGIN_DB, (
        f"归一后真峰 {after_tp:.2f} dBTP，超门限 -1.0"
    )
    assert abs(after_i - _TARGET.integrated_lufs) < abs(before_i - _TARGET.integrated_lufs), (
        "归一之后必须比之前更贴近目标，否则这一遍是白编的"
    )


def test_loudnorm_branch_on_real_hot_audio(
    repo_root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """真 ffmpeg 端到端：**增益够不着**的热片必须落回 loudnorm 路，并由同一套门限验收。

    这条与上面那条是一对：那条钉"该走增益就走增益"，这条钉"不该走增益时增益路不许抢"。
    可行性判据要是被写成恒真（或判据用错了数），热片会被纯增益顶穿真峰，
    这条就红在"路径不是 loudnorm"或"真峰超门限"上。

    素材照真机热片的**形状**做：四正弦床经 `pow(...,400)` 深度脉冲调制、抬 +9 dB，
    再落 s16（`aformat=sample_fmts=s16` 走 `av_clip_int16`，即硬削）——平顶因此能穿过
    AAC 128k，真峰留在 0 dBTP 之上（与 test_mix 的 `hot_original_source` 同一个手法）。
    真机实测（8.1.1-essentials，12 s，连跑两次逐位相同）：归一前
    `I=-12.80 LUFS / Peak=+0.40 dBFS`，crest **13.20 dB**——真成片
    `intro_narration_275746` 是 13.00 dB，同一档。
    判据：gain=-1.20 dB 之后真峰预计 -0.80，高于滤镜要的 -2.50（也高于门限 -1.00），
    纯增益到不了目标响度而不削顶，**压缩是真的需要**。
    归一后实测 `I=-14.80 / Peak=-2.40`：偏离 0.80 LU，在生产容差 2.0 与门禁窗口 2.5 之内，
    真峰在门限 -1.0 之内——loudnorm 路照样要过复核，不是"走了压缩就算交差"。
    """
    ffmpeg = resolve_ffmpeg()
    film = tmp_path / "hot_film.mp4"
    # `pow(a,b)` 里的逗号在滤镜图语法中是滤镜分隔符，必须转义。
    _build_film(
        ffmpeg,
        film,
        "12",
        "aformat=sample_fmts=fltp,"
        "volume=pow(0.5+0.5*sin(2*PI*0.5*t)\\,400):eval=frame,"
        "volume=9.0dB,aformat=sample_fmts=s16",
    )

    before_i, before_tp = _real_gate(ffmpeg, film)
    assert before_tp > 0.0, (
        f"素材必须真的削顶（实测 {before_tp:.2f} dBTP），否则这条用例在量空气"
    )
    assert not _gain_fits(before_i, before_tp), (
        f"素材 crest {before_tp - before_i:.2f} dB 不够大就会走增益路，该换素材"
    )

    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    after_i, after_tp = _real_gate(ffmpeg, film)
    assert _LOG_LOUDNORM in caplog.text, "热片必须落回 loudnorm 路"
    assert _LOG_GAIN not in caplog.text, "判据说不够用就不许先试一遍增益（白送一次有损代）"
    assert abs(after_i - _TARGET.integrated_lufs) <= loudness._TOLERANCE_LU, (
        f"归一后 {after_i:.2f} LUFS，出生产容差 {loudness._TOLERANCE_LU} LU"
    )
    assert after_tp <= _TARGET.true_peak_dbtp + loudness._TP_GATE_MARGIN_DB, (
        f"归一后真峰 {after_tp:.2f} dBTP，超门限 -1.0"
    )


# ---- Phase C 接线证明 ----


def _one_segment_plan(tmp_path: Path) -> tuple[PlanData, str]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        strategy=StrategySpec(),
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0)],
    )
    return plan, str(source)


def test_export_plan_runs_loudness_after_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase C 必须真被调用：它是成片响度的唯一负责人，漏调等于回到没人管响度的状态。"""
    plan, source = _one_segment_plan(tmp_path)
    out = tmp_path / "final.mp4"
    calls: list[str] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda path, **_kw: calls.append(Path(path).name),
    )
    encoder.export_plan(
        plan,
        {"ep1": source},
        out,
        tmp_path / "work",
        loudness_target=loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5),
    )
    assert calls == ["final.mp4"]


def test_export_plan_skips_loudness_when_target_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`loudness_target=None` 是测试缝，不是「零加工模式」的开关。

    生产只有一个调用点（`api/export.py:255`）且无条件传值；仓库里「零加工」指的是**视频包装**
    （不加字幕不遮罩），raw_clip 一样要过 scale/crop/eq/atempo + x264 重编码，
    而且 Task 9 的出口判据要求九个模式全部落在响度窗口内——给 raw_clip 开口子会把它打破。
    """
    plan, source = _one_segment_plan(tmp_path)
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("归一不该被调用")),
    )
    encoder.export_plan(plan, {"ep1": source}, tmp_path / "final.mp4", tmp_path / "work")
