"""kokoro TTS worker：在隔离 venv（tts-venv，Python 3.11 + torch + kokoro）内运行。

协议（stdout 逐行 JSON，stdin 同；与 indextts_worker 同构）：
  就绪行: {"ready": true, "device": "cuda"|"cpu"}
  请求:   {"id": "...", "kwargs": {"pieces": ["块1", ...], "voice_pt": "路径", "out": "路径"}}
  应答:   {"id": "...", "ok": true} 或 {"id": "...", "ok": false, "error": "..."}

切块在主进程做（text_split.split_long_text 单一真相），worker 收整块列表逐块
推理后 numpy 拼接落单文件——venv 进程不能 import dramaclip，worker 必须自包含。
模型加载一次常驻；长文本的内存与耗时靠块边界可控（与主进程旧实现同语义）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_SAMPLE_RATE = 24000


def main() -> int:
    cfg = json.loads(sys.argv[1])
    model_dir = Path(cfg["model_dir"])
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415
    from kokoro import KPipeline  # noqa: PLC0415
    from kokoro.model import KModel  # noqa: PLC0415

    kmodel = KModel(
        config=str(model_dir / "config.json"), model=str(model_dir / "kokoro-v1_1-zh.pth")
    )
    pipeline = KPipeline(lang_code="z", model=kmodel)

    def _emit(obj: dict[str, Any]) -> None:
        os.write(real_stdout, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    _emit({"ready": True, "device": str(getattr(kmodel, "device", "cpu"))})
    request: dict[str, Any] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            kwargs = request["kwargs"]
            pieces = [str(p) for p in kwargs["pieces"]] or [""]
            segments: list[Any] = []
            for piece in pieces:
                for _gs, _ps, audio in pipeline(piece, voice=str(kwargs["voice_pt"])):
                    segments.append(np.asarray(audio))
            audio_np = np.concatenate(segments) if segments else np.zeros(0, dtype="float32")
            out = Path(str(kwargs["out"]))
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), audio_np, _SAMPLE_RATE)
            _emit({"id": request.get("id"), "ok": True})
        except Exception as exc:  # noqa: BLE001 - 单次合成失败按应答回传，不炸 worker
            _emit({
                "id": request.get("id"),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
