"""Edge 引擎的词界：合成时显式要词界事件，每次合成都落边车。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.tts.engines import edge
from dramaclip.engines.tts.text_split import split_long_text


def _sidecar(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".cues.json")


class _Communicate:
    """记下构造参数的替身；要不要给词界由类属性决定。"""

    boundaries: list[Any] = []
    word_cues = True

    def __init__(self, text: str, voice: str, boundary: str | None = None) -> None:
        _Communicate.boundaries.append(boundary)
        self.text = text

    async def stream(self) -> Any:
        yield {"type": "audio", "data": self.text.encode("utf-8")}
        if _Communicate.word_cues and self.text:
            yield {
                "type": "WordBoundary",
                "text": self.text[0],
                "offset": int(0.5 * 1e7),
                "duration": int(0.25 * 1e7),
            }


@pytest.fixture
def fake_edge(monkeypatch: pytest.MonkeyPatch) -> type[_Communicate]:
    _Communicate.boundaries = []
    _Communicate.word_cues = True
    monkeypatch.setitem(sys.modules, "edge_tts", type("m", (), {"Communicate": _Communicate}))
    return _Communicate


def test_edge_asks_for_word_boundaries(fake_edge: type[_Communicate], tmp_path: Path) -> None:
    """库默认只给句边界：不显式要词界，.cues.json 永远不会落下，字幕只能是按字数估的。"""
    out = tmp_path / "n0.mp3"

    edge.EdgeTtsEngine().synthesize("就一句话。", "zh-CN-YunxiNeural", out)

    assert fake_edge.boundaries == ["WordBoundary"]
    cues = json.loads(_sidecar(out).read_text(encoding="utf-8"))
    assert [cue["text"] for cue in cues] == ["就"], "词界文本、起止秒"
    assert (cues[0]["start"], cues[0]["end"]) == (0.5, 0.75)


def test_an_empty_cue_sidecar_is_still_written(
    fake_edge: type[_Communicate], tmp_path: Path
) -> None:
    """没拿到词界也落边车：「有没有边车」是旧配音要不要补词界的记号。"""
    fake_edge.word_cues = False
    out = tmp_path / "n0.mp3"

    edge.EdgeTtsEngine().synthesize("就一句话。", "zh-CN-YunxiNeural", out)

    assert json.loads(_sidecar(out).read_text(encoding="utf-8")) == []


def test_multi_chunk_synthesis_merges_cues_with_block_offsets(
    fake_edge: type[_Communicate], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "第一段解说。" * 80  # 480 字 → 多块
    chunks, _ = split_long_text(text)
    assert len(chunks) > 1
    # 每块实测 2.0 秒：第二块的词界要整体后移一个块长
    monkeypatch.setattr(edge, "audio_duration_s", lambda _path: 2.0)
    out = tmp_path / "n0.mp3"

    edge.EdgeTtsEngine().synthesize(text, "zh-CN-YunxiNeural", out)

    cues = json.loads(_sidecar(out).read_text(encoding="utf-8"))
    assert [cue["start"] for cue in cues] == [0.5 + 2.0 * index for index in range(len(chunks))]
    assert not list(tmp_path.glob("*parts*")), "分块临时目录（连同块边车）必须清干净"
