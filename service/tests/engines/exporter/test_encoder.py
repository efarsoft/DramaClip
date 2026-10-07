"""engines.exporter.encoder：命令构建（真实 ffmpeg 执行由 DoD 端到端覆盖）。"""

from __future__ import annotations

import random

from dramaclip.engines.exporter import encoder
from dramaclip.engines.exporter.encoder import cut_segment_args
from dramaclip.engines.subtitle import caption_font


def test_cut_segment_args_original_audio() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        tts_audio=None,
        rng=random.Random(42),
    )
    joined = " ".join(args)
    assert "-ss 1.500" in joined and "-to 8.250" in joined
    assert "scale=1060:1886:force_original_aspect_ratio=decrease" in joined, "微缩放后等比适配"
    assert "pad=1080:1920:" in joined, "不足处补黑（保持源比例，不裁不拉）"
    assert "crop=" not in joined, "不再有 9:16 裁窗（16:9 就是 16:9）"
    assert "eq=contrast=" in joined, "消重色彩抖动"
    assert "atempo=" in joined, "微变速"
    assert "-map_metadata -1" in joined, "元数据擦除"
    assert "-ar 48000" in joined, "采样率统一（concat 流复制防语速失真）"
    assert "amix" not in joined


def test_cut_segment_args_narration_mixes_tts() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=0,
        end=10,
        audio="narration",
        tts_audio="intro.mp3",
        rng=random.Random(7),
    )
    joined = " ".join(args)
    assert "amix=inputs=2" in joined
    assert "volume=0.1" in joined, "旁白段原声压低"
    assert "intro.mp3" in joined


def test_burned_subtitles_render_with_the_bundled_face() -> None:
    """烧字幕的命令必须带 `fontsdir`：只给族名的话 libass 去系统字体里找，找不到就
    静默换一个，而拆行上限是按随包那份字面标定过的（实测步进差 0.691em vs 0.789em）。
    """
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=0,
        end=10,
        audio="original",
        tts_audio=None,
        rng=random.Random(7),
        ass_path="seg_000.ass",
    )
    joined = " ".join(args)
    ass_option = f"ass=seg_000.ass:{caption_font.fontsdir_option(caption_font.caption_font())}"
    assert ass_option in joined, f"字幕滤镜没带上随包字体目录：{joined}"


def test_original_audio_branch_carries_the_segment_peak_ceiling() -> None:
    """原声直通段也必须过段级真峰天花板，且**逐字等于**两条分支共用的那一处构造。

    漏点来历（真机九模式门禁）：天花板原先只挂在混音分支，`else` 这条只有 `atempo`，
    源素材自己的热度原样穿过 AAC 128k 进成片——九部真成片里七部 `input_tp` 是
    −3.77…−2.17 dBTP，超标的两部 **+3.38 / +1.88** 恰好就是带 `original` 段的那两部。

    断言 `af.endswith(_peak_ceiling_filter())` 而不是断言"含有 alimiter"：前者钉的是
    **两条分支同源**，把 f-string 在 `else` 里再抄一份（数字写死）就红；后者不会。

    两个选项不可省（`-h filter=alimiter` 真机输出：`level <boolean> auto level
    (default true)`、`latency <boolean> compensate delay (default false)`）：
    - `level=disabled`：默认的自动电平按 1/limit 把输出再抬 +3.0 dB，天花板等于没设。
      真机实测同一最坏情况求和，`level=enabled` → **+0.19 dBTP**，比 -3.0 dBFS 的
      天花板还高 3.19 dB；原声直通段实测 **+1.34 / +0.28 dBTP**（两档素材）。
    - `latency=true`：alimiter 是前瞻限幅器，默认不补偿延迟，实测把整段音频推后 4.98 ms；
      每段各自映射视频，不补偿就是段段音画恒定错位。

    诚实边界：字符串断言只能证明"挂上了"，证明不了"限得住"。真机量出来的 dBTP
    （含"剥掉限幅器必须超标"的对照组与两个变异）在 tests/engines/exporter/test_mix.py。
    """
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        tts_audio=None,
        rng=random.Random(42),
    )
    assert "-filter_complex" not in args, "无旁白音频时必须走单路原声，不该声明第二路输入"
    af = args[args.index("-af") + 1]
    ceiling = encoder._peak_ceiling_filter()
    assert af.startswith(encoder._audio_format_filter()), (
        f"原声直通段的 -af 应以两条分支共用的格式级开头：{af!r}"
    )
    assert af.endswith(ceiling), (
        f"原声直通段挂的不是两条分支共用的那一处天花板（-af={af!r}，期望以 {ceiling!r} 结尾）"
    )
    assert af.index("atempo=") < af.index("alimiter="), (
        "限幅器必须在 atempo 之后（= 进 AAC 前最后一级）：alimiter 的 limit 只约束它自己的"
        "输出，后面再重采样会重新长出采样间过冲，天花板被下游悄悄作废"
    )
    assert af.index("aformat=") < af.index("alimiter="), (
        "格式级必须在限幅器**之前**：挂在限幅器之后等于限完再重采样，实测把段真峰从 "
        "-0.3 抬到 +0.1 dBTP（数字见 encoder._SEGMENT_CHANNEL_LAYOUT 的注释）"
    )
    assert ":level=disabled:" in af, "少了它 alimiter 会自动电平回抬，天花板形同不存在"
    assert af.endswith(":latency=true"), "少了它前瞻延迟不补偿，段段音画错位 4.98 ms"
    # 混音分支读的必须是同一处构造（同源，不许各写一份）
    mixed = " ".join(
        cut_segment_args(
            "src.mp4", "seg.mp4", start=0, end=10, audio="narration",
            tts_audio="intro.mp3", rng=random.Random(7),
        )
    )
    assert f",{ceiling}[a]" in mixed, "混音分支那道天花板不许被顺手改掉或改窄"
    # 天花板绝对值只在这一处钉死：改它必须带着实测理由（推导过程写在常量注释里）。
    # 其余断言一律读常量算派生值，下一次重新推导就不用改五处数字。
    assert encoder._SEGMENT_PEAK_CEILING_DBFS == -9.0, "改天花板值必须带着实测理由一起改"


def test_both_branches_force_one_channel_layout() -> None:
    """两条分支（含 amix 的**两路输入**）必须读同一处格式级，把布局钉成同一个值。

    漏点来历（真机实测）：`amix` 在"一路 mono 旁白 + 一路 stereo 原声"上协商出 mono，
    把原声**下混**；原声直通段跟着源走 stereo。Phase B 是 `-c copy`，两种布局照单拼进
    同一条音轨——实测 236 mono / 472 stereo（真成片 `ultra_short_hook_2c9b87` 同法
    177 mono / 533 stereo）。后果是 ebur128 一次运行吐 **2 块** Summary、连跑三次
    integrated 极差 0.6 LU，门禁与 Phase C 取的都是最后一块（只覆盖后半段）。

    断言的是**三处同源**而不是"含有 aformat"：混音分支那两路各写一份、或直通分支写死
    一个 `aformat=...stereo`，字符串断言全都照绿，而改布局只会改一半——正是本缺陷本身。
    声学证据（真渲染 + 真 concat + 门禁那条命令连跑三次）在
    tests/engines/exporter/test_mix.py::test_delivered_track_has_one_channel_layout。
    """
    fmt = encoder._audio_format_filter()
    assert fmt == "aformat=sample_rates=48000:channel_layouts=stereo", (
        "格式级串改了：布局/采样率是交付音轨的不变量，改它要带着真机 concat 的实测一起改"
    )

    original = cut_segment_args(
        "src.mp4", "seg.mp4", start=1.5, end=8.25, audio="original",
        tts_audio=None, rng=random.Random(42),
    )
    af = original[original.index("-af") + 1]
    assert af.count("aformat=") == 1 and af.startswith(fmt), (
        f"原声直通段没有以共用格式级开头（-af={af!r}）"
    )
    # 输出侧的 -ar 与滤镜侧的 sample_rates 必须同源，不许一处改了另一处没改
    assert original[original.index("-ar") + 1] == str(encoder._SEGMENT_SAMPLE_RATE)
    assert f"sample_rates={encoder._SEGMENT_SAMPLE_RATE}:" in fmt

    mixed = cut_segment_args(
        "src.mp4", "seg.mp4", start=0, end=10, audio="narration",
        tts_audio="intro.mp3", rng=random.Random(7),
    )
    graph = mixed[mixed.index("-filter_complex") + 1]
    assert graph.count("aformat=") == 2, (
        f"混音分支必须给 amix 的**两路输入**都钉格式（实测 {graph.count('aformat=')} 处）："
        "只钉一路，amix 照样协商出 mono 并把另一路下混"
    )
    for leg in ("[0:a]", "[1:a]"):
        chain = graph[graph.index(leg):]
        assert chain.startswith(f"{leg}{fmt}"), (
            f"{leg} 那一路没有以共用格式级开头：{chain[:120]!r}"
        )
    assert f"channel_layouts={encoder._SEGMENT_CHANNEL_LAYOUT}" in fmt


def test_fade_transition_pairs_video_and_audio_before_limiter() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=0,
        end=8,
        audio="original",
        tts_audio=None,
        rng=random.Random(1),
        transition="fade",
    )
    joined = " ".join(args)
    vf = args[args.index("-vf") + 1]
    af = args[args.index("-af") + 1]
    assert "fade=t=in:st=0:d=0.180" in vf
    assert "fade=t=out:" in vf
    assert "afade=t=in:" in af
    assert "afade=t=out:" in af
    assert af.endswith(encoder._peak_ceiling_filter()), f"限幅器必须仍是进 AAC 前最后一级：{af}"
    assert af.index("afade=") < af.index("alimiter=")
    assert "flash" not in joined


def test_cut_has_no_video_fade_but_short_afade() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=0,
        end=5,
        audio="original",
        tts_audio=None,
        rng=random.Random(1),
        transition="cut",
        fade_in_s=0.0,
        fade_out_s=0.0,
        afade_in_s=0.10,
        afade_out_s=0.10,
    )
    vf = args[args.index("-vf") + 1]
    af = args[args.index("-af") + 1]
    assert "fade=" not in vf
    assert "afade=t=in:st=0:d=0.100" in af
    assert af.endswith(encoder._peak_ceiling_filter())


def test_cut_segment_args_band_erasure_delogo() -> None:
    """带擦除（2026-10-06 裁决「直接覆盖原始字幕」）：有 band 才有 delogo，
    矩形按微缩放后的内容区折算、含居中 pad 偏移、不出画布；无 band 零滤镜。"""
    band = (0.7174, 0.8291)
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.0,
        end=3.0,
        audio="narration",
        tts_audio=None,
        rng=random.Random(42),
        band=band,
    )
    joined = " ".join(args)
    assert "delogo=" in joined, "有 band 必须有 delogo 擦除"
    scale = next(a for a in args if a.startswith("scale="))
    scaled_h = int(scale.split(":")[1].split(":")[0])
    rect = joined.split("delogo=")[1].split(",")[0]
    parts = dict(p.split("=") for p in rect.split(":"))
    y, h = int(parts["y"]), int(parts["h"])
    top_px = round(0.7174 * scaled_h)
    assert y == max(1, round((1920 - scaled_h) / 2) + top_px), "y = pad 偏移 + 带顶×内容高"
    assert h == round((0.8291 - 0.7174) * scaled_h), "h = 带高×内容高"
    assert y + h <= 1919, "delogo 区域四周须留 1px 边界"

    clean = cut_segment_args(
        "src.mp4",
        "seg2.mp4",
        start=1.0,
        end=3.0,
        audio="narration",
        tts_audio=None,
        rng=random.Random(42),
    )
    assert "delogo=" not in " ".join(clean), "无 band 不加滤镜，与现状逐字节一致"
