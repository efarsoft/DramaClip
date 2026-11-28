"""配音替身共用的落盘：与真引擎同契约——每次合成都落词界边车（没有词界也落空的）。

缺边车的配音会被当成「启用词界之前的旧产物」去补词界（多调一次引擎，见
`synthesis._refresh_cues`）。替身不照做，「同文案只合成一次」这类断言量出来的
就不是生产行为。

引擎层替身（StubTts/BrokenTts）：直接传给 pipeline/plan 的 TTS 槽位用，不走
synthesis 缓存层。真引擎对空文案会失败（ffprobe check=True）——七份手抄替身里
四份漂移掉了这条检查，这里钉一次处处同款（「假 TTS 须与真引擎同契约」的教训）。
"""

from __future__ import annotations

from pathlib import Path

CUES_SUFFIX = ".cues.json"

_EMPTY_CONTRACT_MSG = "TTS 空文案：槽位未被语言层填充"


def write_audio(out_path: Path, data: bytes) -> None:
    """写音频，并在旁边落一个空的词界边车。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    out_path.with_name(f"{out_path.stem}{CUES_SUFFIX}").write_text("[]", encoding="utf-8")


class StubTts:
    """正常合成替身。``content="text"`` 文件内容即文案（串音取证比文件名强：
    文件名对而内容错也能抓住）；``"empty"`` 落 0 字节（时长探测打桩的场景）。
    ``fail_substrings`` 命中 out_path 的段直接失败（云端降级/重试路径用）。"""

    def __init__(
        self,
        content: str = "empty",
        fail_substrings: tuple[str, ...] = (),
    ) -> None:
        self.content = content
        self.fail_substrings = fail_substrings

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        if text.strip() == "":
            raise RuntimeError(_EMPTY_CONTRACT_MSG)
        if any(bad in str(out_path) for bad in self.fail_substrings):
            raise RuntimeError("云端不可达")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8") if self.content == "text" else b"")
        return out_path


class BrokenTts:
    """云端不可达：每次合成都抛错，方案必须随之失败。"""

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        raise RuntimeError("云端不可达")
