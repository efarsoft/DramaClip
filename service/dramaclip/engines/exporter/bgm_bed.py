"""BGM 床混音：整片铺配乐床（响度归一 + 循环 crossfade + 人声躲床）。

自 encoder.py 拆出（拆分专项）：BGM 床混音是导出管线的独立后处理——
输入是成片 + 曲目，输出是混好音的成片（视频轨 copy）。被 encoder.export_plan
调用；BGM 常量与函数经 encoder 模块 re-export（`as` 语法），verify_modes
真机门禁按名字读常量的契约不变。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from dramaclip.engines.exporter import loudness
from dramaclip.infra.ffmpeg import probe as ffprobe_mod
from dramaclip.infra.ffmpeg import runner

_LOGGER = logging.getLogger(__name__)

# BGM 床（C 项接线 → 批3 听感治理升级）：床目标响度、回退音量与尾淡出。
# 床目标 −28 LUFS 的锚：干音契约 −13 LUFS（level_fix 参考带）再低 15 LU——床是
# 连续情绪层不抢人声；固定 0.15 时代曲目 master 实测 −9~−14 LUFS、线性增益
# −16.5 dB 落床 −25~−30 LUFS，取其中位为锚（改这两个数要重听，别挑）。
# 量不到曲目响度时回退 _BGM_BED_VOLUME 固定增益（增强项不挡片）。
_BGM_BED_VOLUME = "0.15"
_BGM_BED_TARGET_LUFS = -28.0
_BGM_TAIL_FADE_S = 1.2
# 循环接长：多副本 acrossfade 替代 stream_loop 硬循环——非无缝曲目在循环点的
# 咔哒消除；曲目过短或副本数超帽（超长片×超短曲）回退硬循环。
_BGM_LOOP_XFADE_S = 0.5
_BGM_LOOP_MAX_COPIES = 8
# 人声躲床：成片混音做 sidechain 触发压床（旁白/原声对白开口床自动退让），
# 与 _SIDECHAIN_COMPRESS 同一模式；attack/release 放慢避免逐音节泵动。
_BGM_DUCK_COMPRESS = "sidechaincompress=threshold=0.05:ratio=4:attack=150:release=400"


def _bed_gain_db(track: Path) -> float | None:
    """曲目 integrated LUFS → 床增益（dB）；量不到返回 None（调用方回退固定增益）。

    床响度归一（批3）：固定 0.15 线性增益下曲目间 6~10 LUFS 的 master 差异
    原样透进成片，换曲=换片感；按「床目标 − 曲目实测」算增益后任何曲目
    落床都同响。ebur128 走门禁同款量法（loudness.measure_integrated_lufs）。
    """
    try:
        reading = loudness.measure_integrated_lufs(track)
    except Exception as exc:  # noqa: BLE001 - 增强项：量不到回退，不挡片
        _LOGGER.warning(
            "BGM 曲目响度测量失败（%s）：床增益回退固定 %s", str(exc)[:120], _BGM_BED_VOLUME
        )
        return None
    return round(_BGM_BED_TARGET_LUFS - reading.integrated_lufs, 2)


def _bed_loop_inputs(track: Path, duration: float, track_dur: float) -> tuple[list[str], str]:
    """床循环输入与子图前缀（产出恒定标签 ``[bedsrc]``）。

    多副本 acrossfade 优先，边界情形回退 stream_loop。返回 (附加输入参数,
    子图前缀)；调用方保证输入 0 是成片、床副本从 1 号输入起编号。acrossfade
    接长的链长 = N*track_dur − (N−1)*crossfade ≥ 成片长（N 多取一副本留
    余量）；amix duration=first 与 -t 再兜底裁齐。
    """
    if duration <= track_dur:
        return ["-i", str(track)], "[1:a]anull[bedsrc];"  # 曲比片长：无需循环
    need = math.ceil(duration / track_dur) + 1
    can_crossfade = track_dur > 2 * _BGM_LOOP_XFADE_S and need <= _BGM_LOOP_MAX_COPIES
    if not can_crossfade:
        # 曲目过短（crossfade 会吃掉大半）或副本数超帽（超长片×超短曲）：
        # 回退硬循环——循环点咔哒风险换可行性，留痕在常量注释。
        return ["-stream_loop", "-1", "-i", str(track)], "[1:a]anull[bedsrc];"
    inputs: list[str] = ["-i", str(track)]
    chain: list[str] = []
    prev = "[1:a]"
    for index in range(2, need + 1):
        inputs += ["-i", str(track)]
        label = "[bedsrc]" if index == need else f"[c{index}]"
        chain.append(f"{prev}[{index}:a]acrossfade=d={_BGM_LOOP_XFADE_S}{label}")
        prev = label
    return inputs, ";".join(chain) + ";"


def _mix_bgm_bed(
    film: Path, track: Path, work_dir: Path, *, lossless_intermediate: bool = False
) -> Path:
    """整片铺 BGM 床，返回混好的文件路径（替换/续加工由调用方决定）。

    v2（批3 听感治理）三升级，画轨不变仍零重编（-c:v copy）：
    - 床响度归一：_bed_gain_db 按曲目实测 LUFS 算 dB，量不到回退固定 0.15；
    - 循环 crossfade：_bed_loop_inputs 多副本接长替代硬循环，循环点无咔哒；
    - 人声躲床：成片混音 sidechain 触发压床（_BGM_DUCK_COMPRESS），旁白/
      原声对白开口床自动退让——与原声衬底避让同一模式、更慢的包络防泵动。
    - lossless_intermediate=True 时音频落 PCM（.mov 容器），供响度归一同链
      续编——开 BGM 成片少一代 AAC 有损。
    其余纪律不变：normalize=0 必须显式关（amix 默认每路乘 1/n 会把人声减半）；
    尾部淡出让收尾不停在硬切的音乐上；混音失败向上抛由调用方降级留痕——
    临时文件里混，原成片不会半途损毁。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".mov" if lossless_intermediate else film.suffix
    mixed = work_dir / f"bgm-mixed{suffix}"
    duration = ffprobe_mod.probe(film).duration_s
    # 曲目是纯音频（probe 要求视频轨会拒收）——用曲库同款 audio_duration_s
    from dramaclip.engines.tts.base import audio_duration_s  # noqa: PLC0415

    track_dur = audio_duration_s(track)
    if track_dur <= 0:
        raise RuntimeError(f"BGM 曲目时长非正（{track_dur:g}s），疑似坏文件")
    fade_start = max(duration - _BGM_TAIL_FADE_S, 0.0)
    loop_inputs, bed_prefix = _bed_loop_inputs(track, duration, track_dur)
    gain_db = _bed_gain_db(track)
    gain_filter = (
        f"volume={gain_db:+.2f}dB" if gain_db is not None else f"volume={_BGM_BED_VOLUME}"
    )
    filter_complex = (
        f"{bed_prefix}"
        f"[bedsrc]{gain_filter}[bedg];"
        f"[0:a]asplit=2[mix_main][duck_trig];"
        f"[bedg][duck_trig]{_BGM_DUCK_COMPRESS}[bedduck];"
        f"[bedduck]afade=t=out:st={fade_start:.3f}:d={_BGM_TAIL_FADE_S}[bed];"
        "[mix_main][bed]amix=inputs=2:duration=first:normalize=0[a]"
    )
    audio_args = (
        ["-c:a", "pcm_s16le"] if lossless_intermediate else ["-c:a", "aac", "-b:a", "192k"]
    )
    runner.run(
        [
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(film),
            *loop_inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy",
            *audio_args,
            "-t", f"{duration:.3f}",
            str(mixed),
        ],
        timeout_s=900,
    )
    if not mixed.is_file() or mixed.stat().st_size == 0:
        raise RuntimeError("BGM 床混音未产出文件")
    return mixed
