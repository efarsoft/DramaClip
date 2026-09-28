"""克隆参考音频清洗：ffmpeg 滤镜链去底噪与频带外噪声，产出 .cleaned.wav。

定位是「一键改善」而非专业修复：highpass 切掉低频隆隆（BGM 低频/环境嗡声），
afftdn 降噪压稳态底噪，lowpass 收掉高频尖刺。人声主频带（80-9000Hz）保留。
与 reference_qc（质检报告）配套：清洗前后各跑一次质检即可对比改善。

采样率与声道随源（克隆引擎自己会重采样）；输出与源同目录（<name>.cleaned.wav）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from dramaclip.infra.ffmpeg import binaries

_TIMEOUT_S = 300
#: 人声频带 + FFT 降噪：highpass 去低频隆隆，afftdn 压稳态底噪，lowpass 收高频尖刺。
_FILTER = "highpass=f=80,afftdn=nf=-25,lowpass=f=9000"


def cleaned_path(path: Path) -> Path:
    return path.with_name(path.stem + ".cleaned.wav")


def clean_reference(path: Path) -> Path:
    """生成清洗后的 wav（<name>.cleaned.wav），失败抛 RuntimeError。"""
    out = cleaned_path(path)
    cmd = [
        binaries.resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path),
        "-af", _FILTER,
        str(out),
    ]
    result = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        cmd, capture_output=True, timeout=_TIMEOUT_S, check=False,
    )
    if result.returncode != 0 or not out.is_file():
        raise RuntimeError(
            f"清洗失败: {result.stderr.decode('utf-8', errors='replace')[-200:]}"
        )
    return out
