"""engines.exporter.encoder：命令构建（真实 ffmpeg 执行由 DoD 端到端覆盖）。"""

from __future__ import annotations

import random

from dramaclip.engines.exporter import encoder
from dramaclip.engines.exporter.encoder import cut_segment_args
from dramaclip.engines.subtitle.mask import drawbox_filter
from dramaclip.infra import config


def test_drawbox_filter_toggle() -> None:
    """遮罩几何随画幅走：默认画幅下沿用原位置，换画幅后不得再按 1080×1920 硬算。"""
    default = (config.EXPORT_WIDTH, config.EXPORT_HEIGHT)
    assert drawbox_filter(True, default) == (
        "drawbox=x=0:y=1689:w=1080:h=230:color=black@0.6:t=fill"
    ), "默认竖屏画幅下的位置与接线前逐字一致"
    assert drawbox_filter(False, default) == ""
    # 画幅改小后仍按比例覆盖底部字幕区（原先这里恒等于 1080×1920，改设置就盖错位置）
    assert drawbox_filter(True, (720, 1280)) == (
        "drawbox=x=0:y=1126:w=720:h=153:color=black@0.6:t=fill"
    )


def test_cut_segment_args_original_audio() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        mask=True,
        tts_audio=None,
        rng=random.Random(42),
    )
    joined = " ".join(args)
    assert "-ss 1.500" in joined and "-to 8.250" in joined
    assert "scale=1080:1920" in joined, "竖屏输出"
    assert "drawbox" in joined, "遮罩开启"
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
        mask=True,
        tts_audio="intro.mp3",
        rng=random.Random(7),
    )
    joined = " ".join(args)
    assert "amix=inputs=2" in joined
    assert "volume=0.2" in joined, "旁白段原声压低"
    assert "intro.mp3" in joined


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
        mask=True,
        tts_audio=None,
        rng=random.Random(42),
    )
    assert "-filter_complex" not in args, "无旁白音频时必须走单路原声，不该声明第二路输入"
    af = args[args.index("-af") + 1]
    ceiling = encoder._peak_ceiling_filter()
    assert af.startswith("atempo="), f"原声直通段的 -af 应以 atempo 开头：{af!r}"
    assert af.endswith(ceiling), (
        f"原声直通段挂的不是两条分支共用的那一处天花板（-af={af!r}，期望以 {ceiling!r} 结尾）"
    )
    assert af.index("atempo=") < af.index("alimiter="), (
        "限幅器必须在 atempo 之后（= 进 AAC 前最后一级）：alimiter 的 limit 只约束它自己的"
        "输出，后面再重采样会重新长出采样间过冲，天花板被下游悄悄作废"
    )
    assert ":level=disabled:" in af, "少了它 alimiter 会自动电平回抬，天花板形同不存在"
    assert af.endswith(":latency=true"), "少了它前瞻延迟不补偿，段段音画错位 4.98 ms"
    # 混音分支读的必须是同一处构造（同源，不许各写一份）
    mixed = " ".join(
        cut_segment_args(
            "src.mp4", "seg.mp4", start=0, end=10, audio="narration", mask=True,
            tts_audio="intro.mp3", rng=random.Random(7),
        )
    )
    assert f",{ceiling}[a]" in mixed, "混音分支那道天花板不许被顺手改掉或改窄"
    assert encoder._SEGMENT_PEAK_CEILING_DBFS == -3.0, "改天花板值必须带着实测理由一起改"
