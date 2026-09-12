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
    assert encoder._SEGMENT_PEAK_CEILING_DBFS == -3.0
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
# 两个夹具共用同一张床，只在其上叠不同的热度处理，免得"最坏情况"各说各话。
_BED_EXPR = (
    "aevalsrc=0.35*sin(2*PI*97*t)+0.3*sin(2*PI*613*t)"
    "+0.2*sin(2*PI*2371*t)+0.15*sin(2*PI*5903*t):s=48000:d=8"
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
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
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
    能带着正真峰穿过 128k 的只有**平顶**：同样这张床抬 +1.4 dB 后落 s16 饱和
    （`aformat=sample_fmts=s16` 用的是 `av_clip_int16`，即硬削），源 `input_tp=+1.98`，
    过 `atempo` + AAC 128k 出来还有 **+1.41 dBTP**。真机片源正是这一档
    （`intro_narration_c3eb30` 整片 +3.38 / `ultra_short_hook_2c9b87` +1.88 dBTP）。
    """
    ffmpeg = _ffmpeg(repo_root)
    d = tmp_path_factory.mktemp("hot-original")
    src = d / "hot.mp4"
    _sh([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8",
         "-f", "lavfi", "-i", _BED_EXPR,
         "-filter_complex",
         "[1:a]aformat=sample_fmts=fltp,volume=1.4,aformat=sample_fmts=s16[a]",
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
        str(src), str(out), start=1.0, end=6.0, audio="original", mask=False,
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

    真机实测（8.1.1-essentials，源 `input_tp=+1.98 dBTP`，走完整条
    `cut_segment_args(audio="original")` 到 AAC 128k 段）：
    剥掉限幅器 → **+1.41 dBTP**；挂上限幅器 → **-0.87 dBTP**（掉 2.28 dB，回到 0 以下）；
    把 `level=disabled` 翻成 alimiter 默认的 `level=enabled` → **+1.34 dBTP**
    （自动电平按 1/limit 又抬回 +3.0 dB，等于只压掉 0.07 dB，天花板形同不存在）。
    三条腿都是真机量的，所以"删限幅器"和"顺手清理掉 level=disabled"这两种改法都会红。

    诚实记账：-0.87 **没有**落进混音分支那条 `天花板 -3.0 + AAC 预算 1.5 = -1.5` 之内。
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
