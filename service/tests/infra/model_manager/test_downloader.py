"""多源下载编排：源降级序、文件清单过滤、URL/落盘布局。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import downloader
from dramaclip.infra.model_manager.registry import builtin_specs

_EPS = {
    "hf_mirror": "https://hf-mirror.com",
    "huggingface": "https://huggingface.co",
    "modelscope": "https://modelscope.cn",
}


def _spec(model_id: str):
    return next(spec for spec in builtin_specs() if spec.model_id == model_id)


def test_sources_domestic_first() -> None:
    assert _spec("sensevoice-small").sources()[0][0] == "modelscope"
    kinds = [kind for kind, _ in _spec("faster-whisper-base").sources()]
    assert kinds == ["hf_mirror", "huggingface"]


def test_source_chain_selected_first_then_domestic() -> None:
    spec = _spec("sensevoice-small")
    assert downloader.source_chain("auto", spec)[0][0] == "modelscope"
    chain = downloader.source_chain("huggingface", spec)
    assert [kind for kind, _ in chain] == ["huggingface", "modelscope", "hf_mirror"]
    # 不支持的源请求不影响回退序
    chain = downloader.source_chain("modelscope", _spec("kokoro-82m"))
    assert [kind for kind, _ in chain] == ["hf_mirror", "huggingface"]


def test_list_tree_hf_filters_junk(monkeypatch) -> None:
    payload: list[dict[str, Any]] = [
        {"type": "file", "path": "model.bin", "size": 480 * 1024 * 1024},
        {"type": "file", "path": ".gitattributes", "size": 512},
        {"type": "file", "path": "README.md", "size": 1024},
        {"type": "file", "path": "example/demo.wav", "size": 2048},
        {"type": "file", "path": "big.bin", "size": 42, "lfs": {"size": 300}},
        {"type": "directory", "path": "empty"},
    ]
    seen: list[str] = []

    def fake(url: str, *, timeout: float = 30.0) -> object:
        seen.append(url)
        return payload

    monkeypatch.setattr(downloader.fetch, "fetch_json", fake)
    files = downloader.list_tree("hf_mirror", "Systran/faster-whisper-base", _EPS)
    assert files == [("model.bin", 480 * 1024 * 1024), ("big.bin", 300)]
    assert seen == [
        "https://hf-mirror.com/api/models/Systran/faster-whisper-base/tree/main?recursive=true"
    ]


def test_list_tree_modelscope_blobs(monkeypatch) -> None:
    payload = {
        "Data": {"Files": [
            {"Path": "model.pt", "Size": 900, "Type": "blob"},
            {"Path": "example/a.wav", "Size": 10, "Type": "blob"},
            {"Path": "docs", "Size": 0, "Type": "tree"},
        ]},
    }
    monkeypatch.setattr(downloader.fetch, "fetch_json", lambda _url, *, timeout=30.0: payload)
    files = downloader.list_tree("modelscope", "iic/SenseVoiceSmall", _EPS)
    assert files == [("model.pt", 900)]


def test_file_url_and_web_url() -> None:
    url = downloader.file_url("hf_mirror", "Systran/faster-whisper-base", "model.bin", _EPS)
    assert url == "https://hf-mirror.com/Systran/faster-whisper-base/resolve/main/model.bin"
    url = downloader.file_url("modelscope", "iic/SenseVoiceSmall", "a b/model.pt", _EPS)
    assert "modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/a%20b/model.pt" in url
    assert downloader.web_url("hf_mirror", "o/r", _EPS) == "https://hf-mirror.com/o/r"
    assert downloader.web_url("modelscope", "o/r", _EPS) == "https://modelscope.cn/models/o/r"


def test_dest_layout_keeps_hf_cache(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-base")
    dest = downloader._dest(tmp_path, spec, "model.bin")
    snapshot = tmp_path / "asr/faster-whisper"
    assert dest == snapshot / "models--Systran--faster-whisper-base/snapshots/main/model.bin"
    other = _spec("kokoro-82m")
    assert downloader._dest(tmp_path, other, "a/b.pth") == tmp_path / "tts/kokoro/a/b.pth"
