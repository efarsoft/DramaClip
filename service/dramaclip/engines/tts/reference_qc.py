"""B6 克隆参考音频质检：inspect_reference(path) -> RefQuality，纯函数报告。

业主质量线：克隆失败落默认音=人设声音变了查不出（批次一已钉显式引擎不回退）。
本模块是**事前**防线：参考音频本身质量差（削波/底噪/太短/静音）时克隆音色必坏，
在用户选参考音频时就告诉他，而不是出片后听出来。

为什么不做 (ref_audio, ref_text) 参考对重转写核对：worker 桥协议只透传
{id, text, voice, out, lang}，没有 ref_text 槽位；IndexTTS2 内部自己转写参考
音频（spk_audio_prompt 零样本克隆）。「参考文本与参考音频不配对」这个问题形态
在当前接入里不存在，做重转写就是给不存在的病开药。

质检是报告不是门禁：任何输入（坏路径/坏文件/缺依赖）都返回结果不 raise，
判差也不阻断合成——用户可能就是要用这段参考，拦死是假门禁；批次一的
「显式引擎不回退」才是硬约束，这里的边界是诚实留痕 vs 替用户做决定。

依赖形状：soundfile+numpy 懒加载 import（kokoro 引擎同款姿势），零新依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

#: 判据阈值（依据注释见各分支）。
_MIN_DURATION_S = 3.0  # 引擎文档口径「任意 3~10 秒人声 wav」的下限
_MAX_DURATION_S = 30.0  # 超过 10s 已偏离推荐区间；30s 才判 fair（长参考还能用，只是拖推理）
_CLIP_THRESHOLD = 0.999  # |sample|≥0.999 视为削波采样点（16bit 满幅 ±1.0）
_CLIP_RATIO_POOR = 0.01  # 削波占比 >1%：克隆音色必带破音质感 → poor
_RMS_QUIET_DBFS = -40.0  # 整体 RMS 低于 -40dBFS：近似静音/音量严重不足 → fair
_RMS_SILENT_DBFS = -60.0  # 低于 -60dBFS 直接当静音 → poor（16bit 噪底约 -96dBFS）
_SNR_FAIR_DB = 15.0  # 帧级信噪比估计 <15dB：底噪明显 → fair
_SNR_POOR_DB = 8.0  # <8dB：语音帧与噪声帧几乎分不开 → poor

#: SNR 估计的帧长：50ms@22050Hz≈1100 样本，够一个音节起落又不至于抹平停顿。
_FRAME_SAMPLES = 1102
#: 噪底取最安静 10% 帧：对齐「语音帧 vs 静音间隙」的能量差口径。
_NOISE_FRACTION = 0.10

_GRADE_ORDER: dict[str, int] = {"good": 0, "fair": 1, "poor": 2}


@dataclass(frozen=True)
class RefQuality:
    """一次质检结果：分档 + 量到的指标 + 人话原因 + 可执行建议。"""

    grade: Literal["good", "fair", "poor"]
    metrics: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


#: 进程内缓存：键 (path, size, mtime_ns)。放模块级而非引擎实例级——indextts2
#: 引擎实例每次 factory.create 都新建（试听/出片各一份），实例级缓存等于没有；
#: 参考音频不会频繁变，size+mtime_ns 已能捕捉重录，无需过期策略。
_CACHE: dict[tuple[str, int, int], RefQuality] = {}


def inspect_reference(path: Path) -> RefQuality:
    """质检一份参考音频。永不 raise：坏路径/坏文件都是 poor+原因，不是异常。"""
    try:
        stat = path.stat()
    except OSError:
        return _poor_unreadable(f"参考音频不存在或不可读：{path}")
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        result = _inspect(*_read_samples(path))
    except Exception as exc:  # noqa: BLE001 - 质检失败也是一条诚实结果（poor+原因）
        result = _poor_unreadable(f"参考音频读不出音频流（{type(exc).__name__}: {exc}）")
    _CACHE[key] = result
    return result


def _read_samples(path: Path) -> tuple[Any, int]:
    """懒加载 soundfile/numpy（与 kokoro 同姿势）：多声道取均值转单声道。"""
    import numpy as np
    import soundfile as sf

    samples, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return np.asarray(samples).mean(axis=1), int(sr)


def _inspect(samples: Any, sr: int) -> RefQuality:
    import numpy as np

    if len(samples) == 0:
        return _poor_unreadable("参考音频没有音频流（0 采样点）")
    duration_s = len(samples) / sr
    rms_dbfs = _dbfs(float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))))
    peak_dbfs = _dbfs(float(np.max(np.abs(samples))))
    clip_ratio = float(np.mean(np.abs(samples) >= _CLIP_THRESHOLD))
    snr_db = _estimate_snr(samples)
    metrics = {
        "duration_s": round(duration_s, 3),
        "rms_dbfs": round(rms_dbfs, 2),
        "peak_dbfs": round(peak_dbfs, 2),
        "clip_ratio": round(clip_ratio, 5),
        "snr_db": round(snr_db, 2),
    }
    reasons: list[str] = []
    suggestions: list[str] = []
    grades: list[str] = []

    if duration_s < _MIN_DURATION_S:
        grades.append("poor")
        reasons.append(f"时长 {duration_s:.1f}s 低于 {_MIN_DURATION_S:.0f}s 下限，音色信息不够克隆")
    elif duration_s > _MAX_DURATION_S:
        grades.append("fair")
        reasons.append(f"时长 {duration_s:.1f}s 超过 {_MAX_DURATION_S:.0f}s，建议截短到 3~10 秒")
    if clip_ratio > _CLIP_RATIO_POOR:
        grades.append("poor")
        reasons.append(f"削波占比 {clip_ratio * 100:.1f}%，克隆音色会带破音")
        suggestions.append("降低录制增益避免削波，重录时留出峰值余量")
    if rms_dbfs <= _RMS_SILENT_DBFS:
        grades.append("poor")
        reasons.append(f"整体音量 {rms_dbfs:.1f}dBFS 近似静音，没有任何可克隆的人声")
    elif rms_dbfs < _RMS_QUIET_DBFS:
        grades.append("fair")
        reasons.append(f"整体音量 {rms_dbfs:.1f}dBFS 过低（<{_RMS_QUIET_DBFS:.0f}dBFS），音量不足")
    if snr_db < _SNR_POOR_DB:
        grades.append("poor")
        reasons.append(f"信噪比过低（约 {snr_db:.1f}dB），底噪与语音几乎分不开")
    elif snr_db < _SNR_FAIR_DB:
        grades.append("fair")
        reasons.append(f"信噪比偏低（约 {snr_db:.1f}dB），底噪明显")
    if not suggestions and ("poor" in grades or "fair" in grades):
        suggestions.append("重录一段 3~10 秒干净人声（安静环境、正常音量、不削波）")

    grade = max(grades, key=lambda g: _GRADE_ORDER[g]) if grades else "good"
    return RefQuality(grade=grade, metrics=metrics, reasons=reasons, suggestions=suggestions)  # type: ignore[arg-type]


def _estimate_snr(samples: Any) -> float:
    """帧级 RMS 分布估计信噪比：语音帧能量 vs 最安静 10% 帧（噪底）的能量差。

    不做谱减法（要 librosa/新依赖，纪律不许）：帧 RMS 分位数差是够用的粗估——
    判「底噪明显/几乎分不开」两档，不需要精确 dB 值。
    """
    import numpy as np

    frames = len(samples) // _FRAME_SAMPLES
    if frames < 4:  # 太短没法分帧：不当噪声问题报，交给时长判据
        return 99.0
    rms = np.sqrt(
        np.mean(
            np.square(samples[: frames * _FRAME_SAMPLES].reshape(frames, _FRAME_SAMPLES),
                    dtype=np.float64),
            axis=1,
        )
    )
    noise_cut = max(1, int(frames * _NOISE_FRACTION))
    noise_floor = float(np.mean(np.sort(rms)[:noise_cut]))
    speech = float(np.mean(np.sort(rms)[-max(1, frames // 2):]))  # 响的一半≈语音帧
    return _dbfs(speech) - _dbfs(noise_floor)


def _dbfs(amplitude: float) -> float:
    import numpy as np

    if amplitude <= 0:
        return -120.0  # 数字静音的地板值，比任何真实噪底都低
    return float(20.0 * np.log10(amplitude))


def _poor_unreadable(reason: str) -> RefQuality:
    return RefQuality(
        grade="poor",
        metrics={},
        reasons=[reason],
        suggestions=["重录一段 3~10 秒干净人声（任意人声 wav，安静环境、正常音量）"],
    )
