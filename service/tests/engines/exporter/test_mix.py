"""编码器混音分支：只要段上带了旁白音频就必须混进成片，且求和后不许削顶。

回归动机（两轴审查 B2）：`full_narration` 每段都是 `ducked`，而取音侧只认
`narration`，导致这个分支对 ducked 从未触发过。本文件锁死编码器的三条腿：
带音即混（不分 narration/ducked）、无音则回退单路原声、求和有天花板。

天花板那两条**真跑 ffmpeg**：字符串里有没有 `alimiter` 与"混音会不会削顶"是两件事，
本批次已经被"断言假象"咬过两次（loudnorm 键名、offset 回喂），所以限幅这件事
一律拿真机量出来的 `input_tp` 说话，并且带一个"把限幅器剥掉必须真的超标"的对照组。
"""

from __future__ import annotations

import math
import random
import re
import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

import pytest

from dramaclip.engines.exporter import encoder, loudness


def _args(audio: str, tts: str | None) -> list[str]:
    return encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0.0, end=3.0, audio=audio,
        tts_audio=tts, rng=random.Random(0),
    )


def test_ducked_segment_mixes_tts() -> None:
    args = _args("ducked", "tts.mp3")
    assert "-filter_complex" in args, "ducked 段未走混音分支，旁白会整条丢失"
    assert "tts.mp3" in args
    assert "volume=0.08" in " ".join(args), "全片解说底噪压到 8%"


def test_narration_segment_mixes_tts() -> None:
    args = _args("narration", "tts.mp3")
    assert "-filter_complex" in args
    assert "volume=0.1" in " ".join(args), "旁白段原声压低 10%"


def test_original_segment_keeps_source_audio() -> None:
    args = _args("original", None)
    assert "-filter_complex" not in args
    assert "-vf" in args


def test_narration_without_audio_falls_back_to_plain() -> None:
    """切段滤镜图：没第二路就不要声明。出片层另有守卫，不许拿这当成功路径。"""
    assert "-filter_complex" not in _args("narration", None), "无音频时不应声明第二路输入"


def test_export_plan_refuses_narration_without_tts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment

    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="narration", narration_id="a"
            )
        ],
        narration_texts=[NarrationText(id="a", text="后面更狠——点进去看全集")],
    )
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)
    monkeypatch.setattr(encoder, "_concat", lambda *_a, **_k: None)
    with pytest.raises(ValueError, match="旁白音频缺失"):
        encoder.export_plan(plan, {"ep1": str(source)}, tmp_path / "out.mp4", tmp_path / "work")


def test_amix_does_not_normalize_inputs() -> None:
    """amix 默认把每路除以输入数（此处各砍 6dB），声明的 0.1/0.08 会变成假数字。"""
    joined = " ".join(_args("narration", "n1.mp3"))
    assert "amix=inputs=2:duration=first:normalize=0" in joined
    assert "volume=0.1," in joined, "narration 段原声须真压到 10%"
    joined_ducked = " ".join(_args("ducked", "n1.mp3"))
    assert "volume=0.08," in joined_ducked and "normalize=0" in joined_ducked


def test_sidechain_ducks_bed_before_amix() -> None:
    """旁白开口时原声再压一截：侧链在 amix 前，限幅器仍收尾。"""
    for audio in ("narration", "ducked"):
        graph = _args(audio, "n1.mp3")[_args(audio, "n1.mp3").index("-filter_complex") + 1]
        assert "asplit=2" in graph, "TTS 既当侧链又进 amix，必须 asplit，标签不能消费两次"
        assert encoder._SIDECHAIN_COMPRESS in graph
        assert graph.index("sidechaincompress") < graph.index("amix"), (
            "侧链必须压床再求和：挂在 amix 之后等于压已经叠好的旁白"
        )
        assert graph.index("amix") < graph.index("alimiter"), "限幅器必须仍是进 AAC 前最后一级"
        assert graph.index("volume=") < graph.index("sidechaincompress"), (
            "固定 volume 是地板，侧链是开口后再压，不能反过来"
        )


# ---- 求和的天花板：关掉 amix 归一化的同时，把它顺带的"削顶保护"也关掉了 ----


def _limit_option() -> str:
    """天花板常量 → alimiter 的线性 `limit`（alimiter 只收线性幅度，不收 dB）。"""
    return f"alimiter=limit={10 ** (encoder._SEGMENT_PEAK_CEILING_DBFS / 20):.4f}"


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
    assert encoder._SEGMENT_PEAK_CEILING_DBFS == -9.0
    joined = " ".join(_args("narration", "n1.mp3"))
    assert f"{_limit_option()}:level=disabled:latency=true" in joined
    assert joined.index("amix") < joined.index("alimiter"), (
        "限幅器挂在 amix 之前等于只限单路：真正会削顶的是求和"
    )
    assert "normalize=0" in joined, "限幅器不许被当成归一化的替代品放回去（Task 7）"


def test_original_branch_carries_the_same_ceiling() -> None:
    """原声直通（`else`）分支必须挂**同一道**天花板，位置在 atempo 之后。

    为什么这条比字符串美观重要（真机实测，`resources/ffmpeg` 8.1.1-essentials，
    片源 `小小球神不好惹` 10 集全部 stereo 48k）：Phase C 之前的九部真成片里，
    七部 `input_tp` 是 −3.77…−2.17 dBTP，两部是 **+3.38**（`intro_narration_c3eb30`）
    与 **+1.88**（`ultra_short_hook_2c9b87`）——恰好就是时间轴里带 `original` 段的那两部。
    混音分支有限幅、直通分支没有，源素材自己的热度原样穿过 `atempo` + AAC 128k 进了成片；
    Phase C 的 loudnorm 只能再限不能"反削顶"，AAC 重编已削平的波形还会过冲，
    于是有界真峰重试也救不回来（实测重试后仍 −0.2 dBTP）。
    """
    ceiling = f"{_limit_option()}:level=disabled:latency=true"
    original = _args("original", None)
    af = original[original.index("-af") + 1]
    assert ceiling in af, (
        f"原声直通段没有天花板（-af={af!r}）：源素材自己热就会带正真峰进成片"
    )
    assert af.index("atempo=") < af.index("alimiter="), (
        "限幅器必须在 atempo 之后（= 进 AAC 前最后一级）：alimiter 的 limit 只约束它自己的"
        "输出，后面再重采样会重新长出采样间过冲，天花板被下游悄悄作废"
    )
    assert ceiling in " ".join(_args("narration", "n1.mp3")), "混音分支那道不许被顺手删掉"
    assert ceiling in " ".join(_args("ducked", "n1.mp3"))


def test_ceiling_constant_drives_both_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两条分支必须读**同一处**天花板：改常量，两条串一起变。

    这条守的是"因式分解"本身。把 f-string 在 `else` 分支里再抄一份（数字写死 -3.0）
    的话，上面那些字符串断言全都照绿，而调天花板只会调一半——正是本批次被咬过两次的
    那种"测试断言假象"。10**(-6/20)=0.501187 → `limit=0.5012`。
    """
    monkeypatch.setattr(encoder, "_SEGMENT_PEAK_CEILING_DBFS", -6.0)
    want = "alimiter=limit=0.5012:level=disabled:latency=true"
    for args in (_args("original", None), _args("narration", "n1.mp3")):
        joined = " ".join(args)
        assert want in joined, f"天花板常量没被这条分支读到：{joined}"
        assert "limit=0.7079" not in joined, "这条分支把 -3.0 写死了，没走同一个常量"


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


# 确定性原声床：四条正弦相加（不用 anoisesrc，理由见 `worst_case` 的 docstring）。
# 各夹具共用同一张床，只在其上叠不同的热度处理，免得"最坏情况"各说各话。
#
# 必须是 **stereo**（真机实测，8.1.1-essentials）：交付段现在一律强制 stereo
# （见 `encoder._SEGMENT_CHANNEL_LAYOUT`），而 AAC 的过冲跟着**编码声道数**走——
# 同一张削平的床（volume=1.4 落 s16、源自报 `input_tp=+1.98`）剥掉限幅器编成段，
# mono 出口实测 **+1.41 dBTP**，stereo 出口只有 **-2.38 dBTP**（差 3.8 dB）。
# 用 mono 床量出来的是"不再交付的那种产物"，对照组也不再超标（用例自己就写着
# "该换素材而不是改断言"）。真片源实测是 `aac / 48000 Hz / 2 ch / stereo`。
#
# 两声道用**不同**的正弦组（97/613/2371/5903 对 101/617/2377/5909 Hz）才是真 stereo；
# 每声道峰值仍是 1.0（0.35+0.3+0.2+0.15），与原 mono 床同热度，好让各档增益的标定可比。
_BED_EXPR = (
    "aevalsrc=0.35*sin(2*PI*97*t)+0.3*sin(2*PI*613*t)"
    "+0.2*sin(2*PI*2371*t)+0.15*sin(2*PI*5903*t)"
    "|0.35*sin(2*PI*101*t)+0.3*sin(2*PI*617*t)"
    "+0.2*sin(2*PI*2377*t)+0.15*sin(2*PI*5909*t):s=48000:d=8"
)


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
    """最坏情况素材：满幅原声床 + 热 TTS 等价音，**两者都必须确定性**。

    原声床用 `aevalsrc` 四条正弦相加而不是 `anoisesrc`：`-h filter=anoisesrc`
    （8.1.1-essentials）真机输出里**没有 seed 选项**，同一条命令连跑三次得到的床实测
    `input_tp` 分别是 -1.11 / -1.97 / -0.77 dBTP——素材自己就在漂，任何数值断言都是掷骰子。
    换成 aevalsrc 之后两次生成的 mp4 **md5 逐字节相同**，床实测 `input_tp=-0.23 dBTP` /
    `input_i=-8.69 LUFS`（峰值 -0.24 dBFS，是最响的合法 PCM 那一档）。

    旁白必须热到**侧链压床之后**求和仍削顶：`volume=11.3`（+3.0 dBTP）在有侧链时
    剥掉限幅器只剩 **-0.12 dBTP**，对照组在量空气。`volume=20` 源自报 **+7.96 dBTP**，
    剥限幅 → **+5.44 dBTP**，限幅后 **-8.43 dBTP**。抬之前必须 `aformat=sample_fmts=fltp`，
    否则 volume 在 s16 上算、抬不过 0 dBFS。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("worst-case-mix")
    bed = d / "bed.mp4"
    tts = d / "tts_hot.wav"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(bed)])
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=997:sample_rate=48000:duration=8",
         "-af", "aformat=sample_fmts=fltp,volume=20", "-c:a", "pcm_f32le", str(tts)])
    assert _input_tp(tts, ffmpeg) == pytest.approx(7.96, abs=0.15)
    return bed, tts


def _render_tp(
    repo_root: Path, bed: Path, tts: Path, out: Path, *, strip_limiter: bool
) -> float:
    """跑真 `cut_segment_args`（不是抄一份滤镜串），量产出段的 input_tp。"""
    args = encoder.cut_segment_args(
        str(bed), str(out), start=1.0, end=6.0, audio="narration",
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
    真机实测（原声床 + 旁白 volume=20 / +7.96 dBTP，走完整条 `cut_segment_args`
    到 AAC 128k 段，含侧链）：剥掉限幅器 → `input_tp=+5.44 dBTP`；挂了限幅器 →
    `input_tp=-8.43 dBTP`，落在天花板 -9.0 dBFS + 1.5 dB AAC 预算之内。两个变异都真跑过：
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
    assert limited <= encoder._SEGMENT_PEAK_CEILING_DBFS + _SEGMENT_AAC_TP_BUDGET_DB, (
        f"限幅后段真峰 {limited:.2f} dBTP，超出天花板 "
        f"{encoder._SEGMENT_PEAK_CEILING_DBFS} dBFS + AAC 预算 {_SEGMENT_AAC_TP_BUDGET_DB} dB"
    )
    assert limited < 0.0, "交付路径上任何一环过 0 dBTP 都是听得见的失真"


# ---- 原声直通段的天花板：源素材自己就在削顶，`else` 分支以前一道限幅都没有 ----


@pytest.fixture(scope="module")
def hot_original_source(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> Path:
    """**进仓就已经削顶**的源素材，形态照真机片源做（确定性：aevalsrc + s16 饱和）。

    为什么必须是削平的而不是"热但不削"的：真机实测（8.1.1-essentials）把同一张
    aevalsrc 床抬 +2.3 dB 但**不落 s16**（保持 fltp、无平顶）编成 AAC 128k，
    源自报 `input_tp=+6.59 dBTP`，而过一遍 `atempo` + AAC 128k 之后只剩
    **-0.39 dBTP**——128k 自己就把没过冲的峰压回去了，`else` 分支根本不 leak。
    能带着正真峰穿过 128k 的只有**平顶**：同样这张床抬 **2.0** 倍后落 s16 饱和
    （`aformat=sample_fmts=s16` 用的是 `av_clip_int16`，即硬削），源 `input_tp=+3.82`，
    过 `atempo` + AAC 128k 出来还有 **+0.76 dBTP**。volume=1.4 那档在 stereo + 段尾
    afade 之后剥限幅只剩 −0.01，对照组在量空气。真机片源正是这一档
    （`intro_narration_c3eb30` 整片 +3.38 / `ultra_short_hook_2c9b87` +1.88 dBTP）。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("hot-original")
    src = d / "hot.mp4"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-filter_complex",
         "[1:a]aformat=sample_fmts=fltp,volume=2.0,aformat=sample_fmts=s16[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(src)])
    assert _input_tp(src, ffmpeg) > 1.0, "素材没热到削顶，这条用例就在量空气"
    return src


@pytest.fixture(scope="module")
def over_fullscale_original_source(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> Path:
    """过 0 dBTP 但**尚未被削成平顶**的源（实测源自报 `input_tp=+2.29`）。

    为什么要第二个夹具、它和 `hot_original_source` 各管什么：
    平顶源上 AAC 的过冲是**跟着削顶深度走的**——同一张床抬 1.4 倍落 s16（源 +1.98）
    限幅后段真峰 -0.87，抬 2.0 倍落 s16（源 +3.59）限幅后**仍是 +0.37**（过冲 3.37 dB）。
    也就是说"限幅器把电平压回 -3.0 dBFS"与"段真峰落进预算"是两件事，前者能做到、
    后者对已削平的源做不到。所以那条用例断言的是方向与量级（见其 docstring）。

    本夹具是另一档：源过 0 dBTP、但采样没有被削平（全程 fltp，不落 s16）。这时限幅器
    交出去的就是干净波形，128k 的过冲回到 0.57–1.06 dB 那一档，段真峰**真的落进**
    与混音分支同一条 `-3.0 + 1.5 = -1.5 dBTP` 预算。真机实测（8.1.1-essentials）
    走完整条 `cut_segment_args(audio="original")`：
        剥掉限幅器 **-0.11 dBTP**（出预算 1.39 dB）→ 本次修复前的漏点
        挂上限幅器 **-2.31 dBTP**（预算内，余量 0.81 dB）
        `level=disabled`→`level=enabled` **+0.28 dBTP**（自动电平把天花板抬回去，出预算）
    三个数都出/入预算分明，所以这条用例是**吃劲**的：剥限幅器或放开 level 都会红。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("over-fullscale-original")
    src = d / "over.mp4"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-filter_complex", "[1:a]aformat=sample_fmts=fltp,volume=1.4[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(src)])
    assert _input_tp(src, ffmpeg) > 0.0, "素材没过 0 dBTP，这条用例就在量空气"
    return src


def _render_original_tp(
    repo_root: Path, src: Path, out: Path, *, variant: str
) -> float:
    """跑真 `cut_segment_args` 的 `else` 分支（audio=original、无旁白），量段的 input_tp。

    三个 variant 共用这一处构造，变异才不可能"只变了一半"：
      - `"limited"`：生产串原样（atempo + 天花板）。
      - `"stripped"`：剥掉限幅器 —— 逐字就是本次修复**之前**的 `else` 分支（只有 atempo）。
      - `"level_enabled"`：把 `level=disabled` 翻成 alimiter 的默认值（`-h filter=alimiter`
        真机输出 `level <boolean> auto level (default true)`），即"顺手清理掉这个选项"的后果。
    """
    args = encoder.cut_segment_args(
        str(src), str(out), start=1.0, end=6.0, audio="original",
        tts_audio=None, rng=random.Random(7),
    )
    index = args.index("-af")
    assert index >= 0, "原声直通分支应该走 -af 而不是 -filter_complex"
    af = args[index + 1]
    if variant == "stripped":
        af = re.sub(r",alimiter=.*$", "", af)
        assert "alimiter" not in af, "剥不掉限幅器说明正则与滤镜串不同步"
    elif variant == "level_enabled":
        if "alimiter" in af:
            af = af.replace("level=disabled", "level=enabled")
            assert "level=enabled" in af, "翻不动 level=disabled 说明滤镜串与用例不同步"
        # 生产串里根本没挂限幅器时，不在这里报字符串错：让调用方的声学断言把 dBTP 报出来
        # （"限幅器整个没了"比"level 选项写错了"严重得多，得由数字说话）。
    else:
        # "limited" 故意**不**在这里断言 alimiter 存在：那样一来"生产串被剥掉限幅器"
        # 会先撞上这条字符串检查，红得没有数字。放行原样渲染，让调用方的声学断言
        # 把真机量出来的 dBTP 报出来——字符串那条由
        # `test_original_branch_carries_the_same_ceiling` 负责，分工不重叠。
        assert variant == "limited", f"未知 variant：{variant!r}"
    args[index + 1] = af
    ffmpeg = _ffmpeg(repo_root)
    _sh([ffmpeg, *args])
    return _input_tp(out, ffmpeg)


def test_original_ceiling_holds_acoustically(
    repo_root: Path, hot_original_source: Path, tmp_path: Path
) -> None:
    """同一段已削顶的源，限幅 vs 剥掉限幅，两边量的都是真机 `input_tp`。

    真机实测（8.1.1-essentials，源 `input_tp=+3.82 dBTP`，走完整条
    `cut_segment_args(audio="original")` 到 AAC 128k 段）：
    剥掉限幅器 → **+0.76 dBTP**；挂上限幅器 → **-6.71 dBTP**；
    把 `level=disabled` 翻成 alimiter 默认的 `level=enabled` → **+1.46 dBTP**。
    三条腿都是真机量的，所以"删限幅器"和"顺手清理掉 level=disabled"这两种改法都会红。

    诚实记账：限幅后 **-6.71 dBTP**，这条用例仍只断言方向（过 0 → 不过 0、掉 ≥1 dB）。
    那 1.5 dB 预算是按"限幅器把波形限干净再交给编码器"实测出来的（0.57–1.06 dB 过冲），
    而这里的源**进仓就是平顶**——限幅器能把电平压回 -3.0 dBFS，却不能把已经削平的顶
    长回来，AAC 重编平顶波形的过冲照旧（同一素材实测过冲 2.13 dB）。所以直通分支的
    天花板是"少漏一点"，不是"保证达标"；剩下的账由 Phase C 的真峰门限与有界重试负责
    （见 loudness.py）。这条用例因此断言的是**方向与量级**（过 0 → 不过 0、掉 ≥1 dB），
    预算那条断言在 `test_original_ceiling_meets_the_documented_aac_budget` 里。
    """
    stripped = _render_original_tp(repo_root, hot_original_source,
                                   tmp_path / "orig_stripped.mp4", variant="stripped")
    limited = _render_original_tp(repo_root, hot_original_source,
                                  tmp_path / "orig_limited.mp4", variant="limited")
    assert stripped > 0.0, (
        f"对照组必须真的过 0 dBTP（实测 {stripped:.2f}）——不过说明素材不够热，"
        "该换素材而不是改断言"
    )
    assert limited < 0.0, (
        f"挂了天花板还过 0 dBTP（实测 {limited:.2f}）：原声直通段会把削顶带进成片"
    )
    assert stripped - limited >= 1.0, (
        f"限幅器只压掉 {stripped - limited:.2f} dB，等于没起作用"
    )
    # 放在声学断言之后再量第三条腿：限幅器整个被删时，上面那两条先带着 dBTP 数字红，
    # 而不是被这一腿的字符串检查挡住（分工见 `_render_original_tp`）。
    auto_level = _render_original_tp(repo_root, hot_original_source,
                                     tmp_path / "orig_autolevel.mp4",
                                     variant="level_enabled")
    assert auto_level > 0.0, (
        f"level=enabled（实测 {auto_level:.2f} dBTP）应当把天花板抵消掉——它若反而达标，"
        "说明素材不够热或 alimiter 语义变了，`level=disabled` 那条断言就不再吃劲"
    )
    assert auto_level - limited >= 1.0, (
        f"自动电平只比 level=disabled 高 {auto_level - limited:.2f} dB，"
        "看不出 1/limit 那次回抬，用例守不住这个选项"
    )


def test_original_ceiling_meets_the_documented_aac_budget(
    repo_root: Path, over_fullscale_original_source: Path, tmp_path: Path
) -> None:
    """直通段也必须落进**与混音分支同一条**预算：`天花板 -3.0 + AAC 预算 1.5 = -1.5 dBTP`。

    这条是"天花板"这个词的字面兑现，和上一条分工明确：上一条用**进仓已削平**的源量
    方向与量级（那种源物理上进不了预算，见其 docstring），这一条用**过 0 dBTP 但未被削平**
    的源量预算本身。真机实测（8.1.1-essentials，源 `input_tp=+2.29 dBTP`）：
        剥掉限幅器        → **-0.11 dBTP**，出预算 1.39 dB（修复前的漏点）
        挂上限幅器        → **-2.31 dBTP**，预算内、余量 0.81 dB
        level=enabled     → **+0.28 dBTP**，出预算 1.78 dB
    素材是确定性的（同一命令两次生成的 mp4 md5 逐字节相同），所以这三个数不靠运气。
    """
    budget = encoder._SEGMENT_PEAK_CEILING_DBFS + _SEGMENT_AAC_TP_BUDGET_DB
    stripped = _render_original_tp(repo_root, over_fullscale_original_source,
                                   tmp_path / "over_stripped.mp4", variant="stripped")
    limited = _render_original_tp(repo_root, over_fullscale_original_source,
                                  tmp_path / "over_limited.mp4", variant="limited")
    assert limited <= budget, (
        f"限幅后原声直通段真峰 {limited:.2f} dBTP，超出天花板 "
        f"{encoder._SEGMENT_PEAK_CEILING_DBFS} dBFS + AAC 预算 "
        f"{_SEGMENT_AAC_TP_BUDGET_DB} dB = {budget:.1f} dBTP"
    )
    assert stripped > budget, (
        f"剥掉限幅器还落在预算内（实测 {stripped:.2f} ≤ {budget:.1f}）——"
        "那这条断言就不吃劲，该换更热的素材而不是放宽预算"
    )
    auto_level = _render_original_tp(repo_root, over_fullscale_original_source,
                                     tmp_path / "over_autolevel.mp4",
                                     variant="level_enabled")
    assert auto_level > budget, (
        f"level=enabled（实测 {auto_level:.2f}）仍落在预算内，"
        "`level=disabled` 这条守卫形同虚设"
    )


# ---- 交付音轨的声道布局：混音段被 amix 收成 mono、直通段跟着源走 stereo ----
#
# 为什么这是一条**声学**用例而不是字符串用例：布局不统一的后果是"任何响度读数都不复现"，
# 只有把两段真渲染拼起来、再拿门禁那条命令量三遍才量得出来。
#
# 真机实测（`resources/ffmpeg` 8.1.1-essentials，修复前）：一段 narration（旁白 mono 24 kHz
# + 原声 stereo 48k）与一段 original 各 5 s，走真 `cut_segment_args` + 真 `encoder._concat`
# 之后
#   `ffprobe -select_streams a:0 -show_entries frame=channel_layout -of csv=p=0 | sort | uniq -c`
#   → **236 mono / 472 stereo**（同法量真成片 `ultra_short_hook_2c9b87` → 177 mono / 533 stereo，
#     `intro_narration_c3eb30` → 399 mono / 9299 stereo，与门禁那两部的读数对得上）
#   门禁那条 `ebur128=peak=true:framelog=quiet` → **2 块 Summary、1 次 Reconfiguring**，
#   最后一块连跑三次 I = **-14.3 / -14.5 / -13.9 LUFS**（极差 0.6 LU）；
#   同一片先解码成 stereo WAV 再量 → **1 块、0 次 Reconfiguring、I = -15.5 三次逐位相同**。
#   即"取最后一块"把整片响度高估了约 1.2 LU，而且它自己就不复现。
# 修复后（本用例钉住的状态）：708 帧全部 stereo、1 块、0 次 Reconfiguring、
# 三次 I = -15.5，且与 WAV 参考**逐位相同**。


def _probe(repo_root: Path, args: list[str]) -> str:
    """跑 ffprobe 并返回 **stdout**（`_sh` 返回的是 stderr，那是 ffmpeg 日志那一侧）。"""
    ffprobe = str(repo_root / "resources" / "ffmpeg" / "ffprobe.exe")
    proc = subprocess.run(  # noqa: S603
        [ffprobe, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    return proc.stdout or ""


@pytest.fixture(scope="module")
def stereo_source_and_mono_tts(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> tuple[Path, Path]:
    """布局用例的素材：stereo 48k 的原声源 + mono 24 kHz 的旁白。

    两路的形态都是照真机量的，不是随手挑的：
      * 原声源 —— 真片源 `小小球神不好惹/1.mp4` 实测 `aac / 48000 Hz / 2 ch / stereo`
        （`ffprobe -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,
        channel_layout`）；
      * 旁白 —— 九模式门禁留下的真 TTS 产物 `preflight.mp3` 实测
        `mp3 / 24000 Hz / 1 ch / mono / 1.0 s`（同一条 ffprobe 命令）。
    正是"mono 旁白 + stereo 原声"这对组合让 `amix` 把求和收成 mono 的。

    夹具自己先量一遍布局：源不是 stereo、旁白不是 mono 就直接红——素材悄悄变均匀的话，
    下面那条用例就成了量空气（本批次被"断言假象"咬过三次）。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("stereo-source")
    src = d / "stereo_src.mp4"
    tts = d / "tts_mono.wav"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(src)])
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=997:sample_rate=24000:duration=8",
         "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(tts)])
    src_layout = _probe(repo_root, ["-v", "error", "-select_streams", "a:0",
                                    "-show_entries", "stream=channel_layout",
                                    "-of", "csv=p=0", str(src)]).strip()
    # 旁白那条量**声道数**而不是 channel_layout：真机实测裸 WAV 头里没有声道掩码，
    # `channel_layout` 报 `unknown`（`channels` 才是 1）。源那条是 AAC in mp4，报 `stereo`。
    tts_channels = _probe(repo_root, ["-v", "error", "-select_streams", "a:0",
                                      "-show_entries", "stream=channels",
                                      "-of", "csv=p=0", str(tts)]).strip()
    assert src_layout == "stereo", f"原声源不是 stereo（实测 {src_layout!r}），用例在量空气"
    assert tts_channels == "1", f"旁白不是单声道（实测 channels={tts_channels!r}），用例在量空气"
    return src, tts


def _gate_pass(repo_root: Path, target: Path) -> tuple[str, loudness.LoudnessMeasurement]:
    """跑一遍**门禁逐字那条**命令，返回 (stderr, 解析出的读数)。

    命令取自 `scripts/verify_modes.py::ebur128`，与 `loudness.measure_gate_args` 同一条：
      ffmpeg -hide_banner -nostats -i <x> -map 0:a:0 \
             -af ebur128=peak=true:framelog=quiet -f null -
    解析走生产解析器 `loudness.parse_gate_reading`（多块时取最后一块，与门禁同判）。
    """
    stderr = _sh([_ffmpeg(repo_root), *loudness.measure_gate_args(str(target))])
    return stderr, loudness.parse_gate_reading(stderr)


def test_delivered_track_has_one_channel_layout(
    repo_root: Path,
    stereo_source_and_mono_tts: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """混音段与原声直通段拼起来，逐帧声道布局必须**只有一种**，响度读数必须**可复现**。

    为什么这条比"字符串里有 aformat"重要（honesty rule 3：量产物，不量命令）：
    Phase B 是 `-c copy` 流复制，它照单全收两段不同的布局，拼出来的音轨中途换布局；
    ffmpeg 于是在换点 `Reconfiguring filter graph`，把测量滤镜 flush 掉——
    一次运行吐出**两块** Summary，门禁与 Phase C 都取最后一块，而最后一块只覆盖后半段。
    实测数字见本节开头那段注释（修复前 236 mono / 472 stereo、2 块、极差 0.6 LU）。
    """
    src, tts = stereo_source_and_mono_tts
    ffmpeg = _ffmpeg(repo_root)
    segments: list[Path] = []
    for index, (audio, tts_arg) in enumerate((("narration", str(tts)), ("original", None))):
        segment = tmp_path / f"seg_{index:03d}.mp4"
        args = encoder.cut_segment_args(
            str(src), str(segment), start=1.0, end=6.0, audio=audio,
            tts_audio=tts_arg, rng=random.Random(11),
        )
        _sh([ffmpeg, *args])
        segments.append(segment)

    film = tmp_path / "film.mp4"
    encoder._concat(segments, film)

    # ffprobe -v error -select_streams a:0 -show_entries frame=channel_layout -of csv=p=0 film.mp4
    layouts = [
        line for line in _probe(
            repo_root, ["-v", "error", "-select_streams", "a:0", "-show_entries",
                        "frame=channel_layout", "-of", "csv=p=0", str(film)]
        ).splitlines() if line
    ]
    assert layouts, "拼出来的片子没有音频帧，用例在量空气"
    histogram = {kind: layouts.count(kind) for kind in sorted(set(layouts))}
    assert set(layouts) == {"stereo"}, (
        f"交付音轨的声道布局不统一：{histogram}"
        "——concat 流复制会把它照单拼进同一条流，测量工具在换点重配滤镜图并多吐一块 Summary"
    )

    stderr, reading = _gate_pass(repo_root, film)
    assert stderr.count("Summary:") == 1, (
        f"门禁那条命令吐了 {stderr.count('Summary:')} 块 Summary（应为 1）："
        "布局中途变了，最后一块只覆盖后半段，门禁与 Phase C 量的都不是整片"
    )
    assert "Reconfiguring filter graph" not in stderr, (
        "滤镜图仍在中途重配（声道布局/采样率不统一的直接症状）"
    )

    repeats = [_gate_pass(repo_root, film)[1].integrated_lufs for _ in range(2)]
    spread = max(repeats + [reading.integrated_lufs]) - min(repeats + [reading.integrated_lufs])
    assert spread <= 0.1, (
        f"同一片子连量三次 integrated 极差 {spread:.2f} LU"
        f"（{reading.integrated_lufs:.2f} / {repeats[0]:.2f} / {repeats[1]:.2f}）："
        "读数不复现，Phase C 的增益预测就没有立足点"
    )

    # 与"先解码成 stereo WAV 再量"的稳定参考对齐：那一路上 reconfig 恒为 0、Summary 恒为 1，
    # 是不受封装影响的整片读数。修复前两者差约 1.2 LU（-14.3…-14.5 对 -15.5）。
    # cmd: ffmpeg -i film.mp4 -map 0:a:0 -ar 48000 -ac 2 -c:a pcm_s16le ref.wav
    wav = tmp_path / "ref.wav"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(film),
         "-map", "0:a:0", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)])
    ref_stderr, ref = _gate_pass(repo_root, wav)
    assert ref_stderr.count("Summary:") == 1, "WAV 参考本身就多块，参考不成立"
    assert abs(reading.integrated_lufs - ref.integrated_lufs) <= 0.1, (
        f"直接量成片 {reading.integrated_lufs:.2f} LUFS 与整片解码参考 "
        f"{ref.integrated_lufs:.2f} LUFS 差 {reading.integrated_lufs - ref.integrated_lufs:+.2f}"
        "——量到的不是整片"
    )


# ---- 语音避让的**实际**深度：0d761d3 把声明值改成 10%/8%，可守卫只量字符串 ----
#
# 业主立案④「解说与原声同音量叠放」的功能修复确实在 09-16 立案之后的 09-17 落地了
# （20%→10%、12%→8%），但直到本次为止，全仓库对"避让"的证据只到 `volume=0.1`
# 出现在命令串里为止——那正是本批次反复咬人的"断言假象"：`normalize=0` 被拿掉、
# `volume=` 被挂到旁白那一路、或 Phase C 的增益把两段一起抬回同一听感电平，
# 字符串用例全都照绿，而业主听到的仍是同一件事。


@pytest.fixture(scope="module")
def cold_bed_and_silent_narration(
    tmp_path_factory: pytest.TempPathFactory, repo_root: Path
) -> tuple[Path, Path]:
    """轻到限幅器完全不介入的原声床 + 数字静默旁白：量出来的差值只可能是鸭子的账。

    两个设计点都不是随手挑的：
      * 床要**冷**：交付链尾挂着 `_peak_ceiling_filter()`（-9.0 dBFS）。共用
        `_BED_EXPR` 那张 -0.23 dBTP 的热床时，`volume=1.0` 对照档会被限幅器压掉
        一截，差值里混进限幅器的账，量不到"声明的 duck 深度"本尊。
      * 旁白要**静默**：amix 是求和，直接量混出来的段只能看到两路之和。把第二路
        换成数字零，产出段就是被压过的原声本体，两档之差即避让深度。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("duck-depth")
    src = d / "cold_bed.mp4"
    silence = d / "silence_tts.wav"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-filter_complex", "[1:a]aformat=sample_fmts=fltp,volume=0.1[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", str(src)])
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
         "-t", "8", "-c:a", "pcm_s16le", str(silence)])
    # 夹具自证：床不够冷（限幅器会出手）的话，下面的差值就不是避让深度。
    # "旁白那一路必须是静音" 不需要单独量——它静不住的话差值会塌向 0 dB，
    # 由下面那条参数化断言当场红掉（amix 是求和，响的那一路盖掉被压的那一路）。
    assert _input_tp(src, ffmpeg) < -15.0, "原声床太热，限幅器会掺进差值里"
    return src, silence


def _render_bed_lufs(
    repo_root: Path,
    src: Path,
    narration: Path,
    out: Path,
    *,
    audio: str,
    force_volume: str | None,
) -> float:
    """跑真 `cut_segment_args` 产出混音段，量整段 integrated LUFS。

    `force_volume` 是对照组：只把 `[bg]` 子链上的 duck 换成给定值，其余滤镜逐字不动。
    生产串里那个 `volume=` 若被摘掉，这里补一个恒等的 1.0 而不是就此报字符串错——
    差值会自己量成 0 dB，"鸭子没了"这件事由数字说话。
    """
    args = encoder.cut_segment_args(
        str(src), str(out), start=1.0, end=6.0, audio=audio,
        tts_audio=str(narration), rng=random.Random(7),
    )
    index = args.index("-filter_complex")
    if force_volume is not None:
        # 只命中 [0:a]…[bg] 那一条子链（`[^;]` + `\[bg\]` 双重锚定），旁白那一路不改
        patched, hits = re.subn(
            r"(\[0:a\][^;]*?)(?:,volume=[\d.]+)?(,atempo=[\d.]+\[bg\])",
            rf"\1,volume={force_volume}\2",
            args[index + 1],
        )
        assert hits == 1, f"[bg] 子链命中 {hits} 处，对照组的形状已与生产滤镜串不同步"
        args[index + 1] = patched
    _sh([_ffmpeg(repo_root), *args])
    return _gate_pass(repo_root, out)[1].integrated_lufs


@pytest.mark.parametrize(
    ("audio", "declared"),
    [("narration", 0.1), ("ducked", 0.08)],
    ids=["narration-10pct", "ducked-8pct"],
)
def test_duck_depth_is_acoustically_real(
    repo_root: Path,
    cold_bed_and_silent_narration: tuple[Path, Path],
    tmp_path: Path,
    audio: str,
    declared: float,
) -> None:
    """声明的避让比例必须等于量出来的避让深度：±0.5 dB 之内。

    声明 0.1 = 20.0 dB、0.08 = 21.9 dB。真机实测（8.1.1-essentials，走完整条
    `cut_segment_args` 到 AAC 128k 段再整段量 integrated）：narration 段 **19.90 dB**、
    ducked 段 **21.90 dB**——两档各差 0.10 / 0.03 dB，说明 0d761d3 那次加深是**真落进
    成片**的，业主立案④的功能修复成立，缺的只是这条量产物的证据。
    这条吃劲的地方在于它比的是**同一条链的两档**：把 `volume=` 摘掉 → 差值实测
    **0.00 dB**；把它从 `[bg]` 挪到旁白那一路 → 同样 0.00 dB。两个变异都会红。
    它**不**管 `normalize=`：归一化对两档等量生效，差分把它抵消了——那一条由
    `test_amix_does_not_normalize_inputs` 守。
    """
    src, narration = cold_bed_and_silent_narration
    ducked = _render_bed_lufs(
        repo_root, src, narration, tmp_path / f"{audio}_ducked.mp4",
        audio=audio, force_volume=None,
    )
    open_bed = _render_bed_lufs(
        repo_root, src, narration, tmp_path / f"{audio}_open.mp4",
        audio=audio, force_volume="1.0",
    )
    depth = open_bed - ducked
    expected = -20.0 * math.log10(declared)
    assert depth == pytest.approx(expected, abs=0.5), (
        f"{audio} 段实测避让 {depth:.2f} dB，声明 {declared:.0%} 应为 {expected:.1f} dB："
        "命令串里的 volume= 与成片里听到的不是同一件事"
    )
