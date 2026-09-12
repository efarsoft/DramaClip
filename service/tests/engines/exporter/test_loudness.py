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
    """替身测量块：数值是编的，键名必须与真 ffmpeg 一致（见 `_STDERR` 的捕获说明）。"""
    return (
        f'{{"input_i": "{integrated}", "input_tp": "{true_peak}", "input_lra": "8.0",'
        f' "input_thresh": "-30.0", "output_i": "{integrated}", "output_tp": "{true_peak}",'
        f' "output_lra": "8.0", "output_thresh": "-24.0",'
        f' "normalization_type": "dynamic", "target_offset": "0.5"}}'
    )


def _stub_run(
    monkeypatch: pytest.MonkeyPatch,
    measurements: list[str],
    *,
    produce_file: bool = True,
    has_audio: bool = True,
) -> list[list[str]]:
    """替身 `_run` + 替身 ffprobe：测量遍按序吐 stderr，归一遍产出（或不产出）staged 文件。"""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        loudness.probe,
        "probe",
        lambda _path: MediaInfo(
            duration_s=1.0, width=1080, height=1920, fps=30.0, has_audio=has_audio
        ),
    )

    def fake_run(args: list[str]) -> str:
        seen.append(list(args))
        if "null" in args:  # 测量遍（-f null）
            index = len([item for item in seen if "null" in item]) - 1
            return measurements[index]
        if produce_file:  # 归一遍：写出 staged 产物
            Path(args[-1]).write_bytes(b"normalized")
        return ""

    monkeypatch.setattr(loudness, "_run", fake_run)
    return seen


def test_normalize_in_place_replaces_file_and_returns_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """顺路径：staged 产物原地替换成片，返回的必须是归一后那次复核实测。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-14.1, -2.0)],
    )
    checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.integrated_lufs == -14.1, "返回的必须是复核（第二遍）实测，不是归一前的"
    assert film.read_bytes() == b"normalized", "成片必须被归一产物原地替换"
    assert len(seen) == 3, "两遍测量 + 一遍归一，缺一不可"


def test_recheck_measures_the_staged_file_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复核必须量 staged 产物：先 replace 再量，超标的那一版就已经坐在成品路径上了。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    seen = _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-14.1, -2.0)],
    )
    loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    recheck_input = seen[-1][seen[-1].index("-i") + 1]
    assert Path(recheck_input).name == "loudnorm_stage.mp4"


def test_recheck_drift_beyond_tolerance_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复核是 Phase C 的验收线：归一后仍偏离目标超容差必须抛，不得放行。"""
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(
        monkeypatch,
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-20.0, -3.0)],  # 复核差 6 LU
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
        [
            _measure_stderr(-23.7, -3.1),
            _measure_stderr(-14.0, -0.4),  # 真峰超 -1.5+0.5
            _measure_stderr(-14.0, -0.4),  # 重试后仍超
        ],
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len([call for call in seen if "null" not in call]) == 2, "抛错前恰好重试过一次"
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
            [
                _measure_stderr(-23.7, -3.1),
                _measure_stderr(-14.0, true_peak),
                # 超线的那一格会触发有界重试：重试复核也喂同一个超标值，让它走到抛错。
                _measure_stderr(-14.0, true_peak),
            ],
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
        [
            _measure_stderr(-23.7, -3.1),  # 源测量
            _measure_stderr(-14.0, -0.4),  # 复核 1：超门限（-1.5 + 0.5 = -1.0）
            _measure_stderr(-14.0, -1.4),  # 复核 2（重试产物）：过门
        ],
    )
    with caplog.at_level("INFO", logger="dramaclip.engines.exporter.loudness"):
        checked = loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert checked.true_peak_dbtp == -1.4, "返回的必须是重试那一版的复核"
    assert film.read_bytes() == b"normalized"
    encodes = [call for call in seen if "null" not in call]
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
        [
            _measure_stderr(-23.7, -3.1),
            _measure_stderr(-14.0, -0.4),  # 复核 1 超标
            _measure_stderr(-14.0, -0.6),  # 复核 2 仍超标
        ],
    )
    with pytest.raises(loudness.LoudnessError, match="真峰值超标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    encodes = [call for call in seen if "null" not in call]
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
        [_measure_stderr(-23.7, -3.1), _measure_stderr(-20.0, -3.0)],  # 复核差 6 LU
    )
    with pytest.raises(loudness.LoudnessError, match="偏离目标"):
        loudness.normalize_in_place(film, target=_TARGET, work_dir=tmp_path / "wn")
    assert len(seen) == 3, "测量+编码+复核各一次；第四次调用出现即说明漂移也走了重试"
    assert film.read_bytes() == b"film"


def test_normalize_without_output_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"film")
    _stub_run(monkeypatch, [_measure_stderr(-23.7, -3.1)], produce_file=False)
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
            str(repo_root / "resources" / "ffmpeg" / "ffmpeg.exe"),
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
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
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
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("归一不该被调用")),
    )
    encoder.export_plan(plan, {"ep1": source}, tmp_path / "final.mp4", tmp_path / "work")
