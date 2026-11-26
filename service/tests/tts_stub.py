"""配音替身共用的落盘：与真引擎同契约——每次合成都落词界边车（没有词界也落空的）。

缺边车的配音会被当成「启用词界之前的旧产物」去补词界（多调一次引擎，见
`synthesis._refresh_cues`）。替身不照做，「同文案只合成一次」这类断言量出来的
就不是生产行为。
"""

from __future__ import annotations

from pathlib import Path

CUES_SUFFIX = ".cues.json"


def write_audio(out_path: Path, data: bytes) -> None:
    """写音频，并在旁边落一个空的词界边车。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    out_path.with_name(f"{out_path.stem}{CUES_SUFFIX}").write_text("[]", encoding="utf-8")
