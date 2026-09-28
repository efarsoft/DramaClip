"""人声分离 worker：在隔离 venv（tts-venv，audio-separator[cpu]）内运行。

与 cosyvoice_worker / indextts_worker 的常驻协议不同，这是一次性进程：一次清洗
一条参考音频，跑完即退（模型加载 + 分离在 CPU 上约 30s，用户点击级操作不值得
常驻占显存/内存）。协议是一行 JSON 到 stdout：
  {"ok": true, "out": "<干声路径>"} 或 {"ok": false, "error": "..."}
诊断日志全部走库内 logger→stderr——stdout 是协议通道，混进日志就是坏帧。

模型是单文件 MDX-Net（UVR_MDXNET_KARA_2.onnx，约 50MB）：模型文件由主进程负责
就位（含 gh-proxy 多源下载，见 vocal_separation.py），worker 只认 --models 里的
本地文件，不做任何下载——下载策略换掉时 worker 不用跟着改。

产物取 (Vocals) 干声（BGM/音效进 (Instrumental)，正是要剥掉的部分），落盘为
44.1kHz 立体声 wav；克隆引擎侧用 librosa/torchaudio 读参考时自带单声道化与
重采样，这里不再二次加工、不偷采样率。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: 与主进程 vocal_separation.MODEL_FILENAME 必须一致：两边各写一份是刻意的——
#: worker 在隔离 venv 里 import 不到主服务包，跨进程共享只能靠约定。
MODEL_FILENAME = "UVR_MDXNET_KARA_2.onnx"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="src", required=True)
    parser.add_argument("--out", dest="out", required=True)
    parser.add_argument("--models", dest="models", required=True)
    args = parser.parse_args()
    try:
        out = separate(Path(args.src), Path(args.out), Path(args.models))
    except Exception as exc:  # noqa: BLE001 - 任何失败都要变成一行协议应答，不能裸崩
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    _emit({"ok": True, "out": str(out)})
    return 0


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def separate(src: Path, out: Path, models_dir: Path) -> Path:
    """跑一次分离，把 (Vocals) 干声原子改名到 out（同目录，残留清干净）。"""
    from audio_separator.separator import Separator

    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    separator = Separator(
        model_file_dir=str(models_dir), output_dir=str(work), output_format="WAV"
    )
    separator.load_model(MODEL_FILENAME)
    stems = separator.separate(str(src))
    vocals = _vocals_of(stems)
    if vocals is None:
        raise RuntimeError(f"分离产物里没有 (Vocals) 干声：{stems}")
    os.replace(work / vocals, out)
    for leftover in stems:  # (Instrumental) 对参考清洗没用，留残就是垃圾文件
        (work / leftover).unlink(missing_ok=True)
    return out


def _vocals_of(stems: list[str]) -> str | None:
    return next((stem for stem in stems if "(Vocals)" in stem), None)


if __name__ == "__main__":
    sys.exit(main())
