"""编码器混音分支：只要段上带了旁白音频就必须混进成片，且求和后不许削顶。

回归动机（两轴审查 B2）：`full_narration` 每段都是 `ducked`，而取音侧只认
`narration`，导致这个分支对 ducked 从未触发过。本文件锁死编码器的三条腿：
带音即混（不分 narration/ducked）、无音则回退单路原声、求和有天花板。

天花板那两条**真跑 ffmpeg**：字符串里有没有 `alimiter` 与"混音会不会削顶"是两件事，
本批次已经被"断言假象"咬过两次（loudnorm 键名、offset 回喂），所以限幅这件事
一律拿真机量出来的 `input_tp` 说话，并且带一个"把限幅器剥掉必须真的超标"的对照组。
"""

from __future__ import annotations

import random
import re
import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder, loudness


def _args(audio: str, tts: str | None) -> list[str]:
    return encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0.0, end=3.0, audio=audio, mask=False,
        tts_audio=tts, rng=random.Random(0),
    )


def test_ducked_segment_mixes_tts() -> None:
    args = _args("ducked", "tts.mp3")
    assert "-filter_complex" in args, "ducked 段未走混音分支，旁白会整条丢失"
    assert "tts.mp3" in args
    assert "volume=0.12" in " ".join(args), "全片解说底噪压到 12%"


def test_narration_segment_mixes_tts() -> None:
    args = _args("narration", "tts.mp3")
    assert "-filter_complex" in args
    assert "volume=0.2" in " ".join(args), "旁白段原声压低 20%"


def test_original_segment_keeps_source_audio() -> None:
    args = _args("original", None)
    assert "-filter_complex" not in args
    assert "-vf" in args


def test_narration_without_audio_falls_back_to_plain() -> None:
    assert "-filter_complex" not in _args("narration", None), "无音频时不应声明第二路输入"


def test_amix_does_not_normalize_inputs() -> None:
    """amix 默认把每路除以输入数（此处各砍 6dB），声明的 0.2/0.12 会变成假数字。"""
    joined = " ".join(_args("narration", "n1.mp3"))
    assert "amix=inputs=2:duration=first:normalize=0" in joined
    assert "volume=0.2," in joined, "narration 段原声须真压到 20%"
    joined_ducked = " ".join(_args("ducked", "n1.mp3"))
    assert "volume=0.12," in joined_ducked and "normalize=0" in joined_ducked


# ---- 求和的天花板：关掉 amix 归一化的同时，把它顺带的"削顶保护"也关掉了 ----


def _limit_option() -> str:
    """天花板常量 → alimiter 的线性 `limit`（alimiter 只收线性幅度，不收 dB）。"""
    return f"alimiter=limit={10 ** (encoder._MIX_PEAK_CEILING_DBFS / 20):.4f}"


def test_mix_limits_the_sum_after_amix() -> None:
    """限幅器必须挂在 amix **之后**，且 `level=disabled`、`latency=true`。

    `-h filter=alimiter`（8.1.1-essentials）真机输出里我们依赖的三项：
        level    <boolean>  auto level (default true)
        limit    <double>   set limit (from 0.0625 to 1) (default 1)
        latency  <boolean>  compensate delay (default false)

    `level=disabled` 不是洁癖，真机实测（0 dBFS 正弦过 `alimiter=limit=0.7079`）：
    默认 `level=true` → `max_volume 0.0 dB`；`level=disabled` → `-3.0 dB`。
    那个默认的 level 是**自动电平**（按 1/limit 把输出抬回去，行为等同 maximizer），
    天花板被它自己抵消掉；而且它对**根本没碰到天花板**的素材照样抬——
    -38.1 dBFS 的安静信号过默认参数变成 **-35.1 dB**（凭空 +3.0 dB）。
    那正是 Task 7 刚消灭的"声明值 ≠ 实际值"，不能从后门放回来。

    `latency=true`：alimiter 是前瞻限幅器，默认不补偿延迟，实测把整段音频推后
    **4.98 ms**（silencedetect 的 silence_end 1.000021 → 1.005）；加上 latency=true
    回到 1.000021（与 anull 逐位相同），时长仍是 3.000000 s、天花板仍是 -3.0 dB。
    每段各自映射 [0:v]，不补偿就是段段音频恒定晚于画面。
    """
    assert encoder._MIX_PEAK_CEILING_DBFS == -3.0
    joined = " ".join(_args("narration", "n1.mp3"))
    assert f"{_limit_option()}:level=disabled:latency=true" in joined
    assert joined.index("amix") < joined.index("alimiter"), (
        "限幅器挂在 amix 之前等于只限单路：真正会削顶的是求和"
    )
    assert "normalize=0" in joined, "限幅器不许被当成归一化的替代品放回去（Task 7）"


# 段产物是 AAC 128k，编码后真峰还要再抬一截，量的是抬过之后的值。
# 真机实测（`resources/ffmpeg/ffmpeg.exe` 8.1.1-essentials）：
# - 已被限到 -3.0 dBFS 的干净信号，128k 编解码只再抬 **0.57–1.06 dB**（四例：合成 narration
#   段 -2.43、合成 ducked 段 -1.94、真源 narration 段 -2.12、真源 ducked 段 -2.18 dBTP）；
# - **已经削平**的信号抬得多得多：真实源集同一 5 s 窗口自身 `input_tp=+0.30`，
#   过 128k 回环变 **+4.04 dBTP**（抬 3.75 dB），换 192k 只到 +0.48（抬 0.18 dB）。
# 平顶削波才是过冲的大头——这正是"先限干净再交给编码器"的理由，也是 1.5 dB 预算的来历
# （四例里最差 1.06，留 0.44 dB 给 ffmpeg 版本漂移；素材是确定性的，所以这条不靠运气）。
_SEGMENT_AAC_TP_BUDGET_DB = 1.5


def _ffmpeg(repo_root: Path) -> str:
    return str(repo_root / "resources" / "ffmpeg" / "ffmpeg.exe")


def _sh(args: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    return proc.stderr or ""


def _input_tp(path: Path, ffmpeg: str) -> float:
    """量的就是 Phase C 第一遍量的那个数：loudnorm 自报的 input_tp（走生产解析器）。"""
    stderr = _sh([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                  "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    return loudness.parse_measurements(stderr).true_peak_dbtp


@pytest.fixture(scope="module")
def worst_case(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> tuple[Path, Path]:
    """最坏情况素材：满幅原声床 + +3.0 dBTP 的"TTS 等价音"，**两者都必须确定性**。

    原声床用 `aevalsrc` 四条正弦相加而不是 `anoisesrc`：`-h filter=anoisesrc`
    （8.1.1-essentials）真机输出里**没有 seed 选项**，同一条命令连跑三次得到的床实测
    `input_tp` 分别是 -1.11 / -1.97 / -0.77 dBTP——素材自己就在漂，任何数值断言都是掷骰子。
    换成 aevalsrc 之后两次生成的 mp4 **md5 逐字节相同**，床实测 `input_tp=-0.23 dBTP` /
    `input_i=-8.69 LUFS`（峰值 -0.24 dBFS，是最响的合法 PCM 那一档）。

    旁白那条的数字也都是真机量的：lavfi `sine` 自带 -18.06 dBFS 峰值，`volume=11.3`
    抬到 **+3.0 dBTP**；抬之前必须 `aformat=sample_fmts=fltp`，否则 volume 在 s16 上算、
    抬不过 0 dBFS（实测被夹在 0.0 dB）。+3.0 dBTP 的旁白不是编出来的：真成片
    `intro_narration_325c84` 的整片 `input_tp` 就是 **+3.26 dBTP**。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("worst-case-mix")
    bed = d / "bed.mp4"
    tts = d / "tts_hot.wav"
    bed_expr = (
        "aevalsrc=0.35*sin(2*PI*97*t)+0.3*sin(2*PI*613*t)"
        "+0.2*sin(2*PI*2371*t)+0.15*sin(2*PI*5903*t):s=48000:d=8"
    )
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", bed_expr,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(bed)])
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=997:sample_rate=48000:duration=8",
         "-af", "aformat=sample_fmts=fltp,volume=11.3", "-c:a", "pcm_f32le", str(tts)])
    assert _input_tp(tts, ffmpeg) == pytest.approx(3.0, abs=0.05)
    return bed, tts


def _render_tp(
    repo_root: Path, bed: Path, tts: Path, out: Path, *, strip_limiter: bool
) -> float:
    """跑真 `cut_segment_args`（不是抄一份滤镜串），量产出段的 input_tp。"""
    args = encoder.cut_segment_args(
        str(bed), str(out), start=1.0, end=6.0, audio="narration", mask=False,
        tts_audio=str(tts), rng=random.Random(7),
    )
    if strip_limiter:
        index = args.index("-filter_complex")
        args[index + 1] = re.sub(r",alimiter=[^;\[]*", "", args[index + 1])
        assert "alimiter" not in args[index + 1], "剥不掉限幅器说明正则与滤镜串不同步"
    ffmpeg = _ffmpeg(repo_root)
    _sh([ffmpeg, *args])
    return _input_tp(out, ffmpeg)


def test_mix_ceiling_holds_acoustically(
    repo_root: Path, worst_case: tuple[Path, Path], tmp_path: Path
) -> None:
    """同一个最坏情况求和，限幅 vs 剥掉限幅，两边量的都是真机 `input_tp`。

    对照组是这条用例的全部意义：素材要是没热到能削顶，"限幅后达标"就是句空话。
    真机实测（原声床 -0.23 dBTP + 旁白 +3.0 dBTP，走完整条 `cut_segment_args`
    到 AAC 128k 段）：剥掉限幅器 → `input_tp=+4.02 dBTP`（采样峰 +4.01 dB，平顶硬削，
    听感就是破音）；挂了限幅器 → `input_tp=-2.43 dBTP`，落在天花板 -3.0 dBFS
    + 1.5 dB AAC 预算之内。两个变异都真跑过：
    `level=disabled`→`level=enabled`（alimiter 的默认值）→ **+0.19 dBTP**，自动电平把
    天花板自己抵消；限幅器从求和挪到旁白单路 → **-0.98 dBTP**，单路限干净了和还是超。
    """
    bed, tts = worst_case
    stripped = _render_tp(repo_root, bed, tts, tmp_path / "stripped.mp4",
                          strip_limiter=True)
    limited = _render_tp(repo_root, bed, tts, tmp_path / "limited.mp4",
                         strip_limiter=False)
    assert stripped > 0.0, (
        f"对照组必须真的削顶（实测 {stripped:.2f} dBTP）——不超标说明素材不够热，"
        "这条用例在量空气，该换素材而不是改断言"
    )
    assert limited <= encoder._MIX_PEAK_CEILING_DBFS + _SEGMENT_AAC_TP_BUDGET_DB, (
        f"限幅后段真峰 {limited:.2f} dBTP，超出天花板 "
        f"{encoder._MIX_PEAK_CEILING_DBFS} dBFS + AAC 预算 {_SEGMENT_AAC_TP_BUDGET_DB} dB"
    )
    assert limited < 0.0, "交付路径上任何一环过 0 dBTP 都是听得见的失真"
