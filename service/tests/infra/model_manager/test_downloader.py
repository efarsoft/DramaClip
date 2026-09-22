"""多源下载编排：源降级序、文件清单过滤、URL/落盘布局、提交号解析与就地迁移。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra.model_manager import downloader, fetch
from dramaclip.infra.model_manager.registry import builtin_specs

_EPS = {
    "hf_mirror": "https://hf-mirror.com",
    "huggingface": "https://huggingface.co",
    "modelscope": "https://modelscope.cn",
}

_SHA = "b" * 40
_LFS_OID = "a" * 64

_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def _spec(model_id: str):
    return next(spec for spec in builtin_specs() if spec.model_id == model_id)


class _Notifier:
    """只记账的 notifier 替身：log 与 model_download 都收进列表供断言。"""

    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []

    def log(self, level: str, message: str) -> None:
        self.logs.append((level, message))

    def model_download(self, model_id: str, percent: float, *, status: str) -> None:
        self.logs.append((status, f"{model_id}:{percent:.0f}"))


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
        {"type": "file", "path": "big.bin", "size": 42, "lfs": {"size": 300, "oid": _LFS_OID}},
        {"type": "file", "path": "odd.bin", "size": 7, "lfs": {"size": 7, "oid": "not-a-sha"}},
        {"type": "directory", "path": "empty"},
    ]
    seen: list[str] = []

    def fake(url: str, *, timeout: float = 30.0) -> object:
        seen.append(url)
        return payload

    monkeypatch.setattr(downloader.fetch, "fetch_json", fake)
    files = downloader.list_tree("hf_mirror", "Systran/faster-whisper-base", _EPS)
    # LFS oid 即内容 SHA256，留下来给落盘后对账；形状不对的（odd.bin）宁缺毋滥退 None
    assert files == [
        ("model.bin", 480 * 1024 * 1024, None),
        ("big.bin", 300, _LFS_OID),
        ("odd.bin", 7, None),
    ]
    assert seen == [
        "https://hf-mirror.com/api/models/Systran/faster-whisper-base/tree/main?recursive=true"
    ]


def test_list_tree_modelscope_blobs(monkeypatch) -> None:
    payload = {
        "Data": {"Files": [
            {"Path": "model.pt", "Size": 900, "Type": "blob", "Sha256": _LFS_OID},
            {"Path": "example/a.wav", "Size": 10, "Type": "blob"},
            {"Path": "docs", "Size": 0, "Type": "tree"},
        ]},
    }
    monkeypatch.setattr(downloader.fetch, "fetch_json", lambda _url, *, timeout=30.0: payload)
    files = downloader.list_tree("modelscope", "iic/SenseVoiceSmall", _EPS)
    assert files == [("model.pt", 900, _LFS_OID)]


def test_file_url_and_web_url() -> None:
    url = downloader.file_url("hf_mirror", "Systran/faster-whisper-base", "model.bin", _EPS)
    assert url == "https://hf-mirror.com/Systran/faster-whisper-base/resolve/main/model.bin"
    url = downloader.file_url("modelscope", "iic/SenseVoiceSmall", "a b/model.pt", _EPS)
    assert "modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/a%20b/model.pt" in url
    assert downloader.web_url("hf_mirror", "o/r", _EPS) == "https://hf-mirror.com/o/r"
    assert downloader.web_url("modelscope", "o/r", _EPS) == "https://modelscope.cn/models/o/r"


def test_dest_layout_keeps_hf_cache(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-base")
    dest = downloader._dest(tmp_path, spec, "model.bin", _SHA)
    snapshot = tmp_path / "asr/faster-whisper"
    assert dest == snapshot / f"models--Systran--faster-whisper-base/snapshots/{_SHA}/model.bin"
    # 解析不到提交号的退化形态：字面 main（体检报 warn「无从对账」，不冒充提交号）
    assert downloader._dest(tmp_path, spec, "model.bin", "main").parent.name == "main"
    other = _spec("kokoro-82m")
    assert downloader._dest(tmp_path, other, "a/b.pth", "main") == tmp_path / "tts/kokoro/a/b.pth"


# ---------------------------------------------------------------- 提交号解析


def test_resolve_revision_accepts_only_forty_hex(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "fetch_json", lambda _url, *, timeout=30.0: {"sha": _SHA.upper()})
    assert downloader.resolve_revision("hf_mirror", "o/r", _EPS) == _SHA
    monkeypatch.setattr(fetch, "fetch_json", lambda _url, *, timeout=30.0: {"sha": "main"})
    assert downloader.resolve_revision("hf_mirror", "o/r", _EPS) is None


def test_resolve_revision_swallows_network_failure(monkeypatch) -> None:
    """解析失败不抛——退化落盘是设计内行为，由调用方向用户如实播报。"""

    def boom(_url: str, *, timeout: float = 30.0) -> object:
        raise OSError("network down")

    monkeypatch.setattr(fetch, "fetch_json", boom)
    assert downloader.resolve_revision("huggingface", "o/r", _EPS) is None
    # ModelScope 没有这个 API 形状，直接 None，不发请求
    assert downloader.resolve_revision("modelscope", "o/r", _EPS) is None


# ---------------------------------------------------------------- 合规落盘


def _fake_hf_apis(monkeypatch, tree: list[dict[str, Any]], *, sha: str | None = _SHA) -> None:
    def fake(url: str, *, timeout: float = 30.0) -> object:
        if url.endswith("/tree/main?recursive=true"):
            return tree
        return {"sha": sha} if sha is not None else {}

    monkeypatch.setattr(fetch, "fetch_json", fake)


def _fake_download(monkeypatch, content: bytes = b"payload") -> list[Path]:
    written: list[Path] = []

    def fake(url: str, dest: Path, size: int, **kwargs: Any) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        written.append(dest)

    monkeypatch.setattr(fetch, "download_file", fake)
    return written


def test_download_from_writes_compliant_hf_cache(tmp_path: Path, monkeypatch) -> None:
    """下载产物必须就是体检认可的合规资产：snapshots/<提交号> + refs + trees 清单。"""
    spec = _spec("faster-whisper-base")
    tree = [{"type": "file", "path": name, "size": 7} for name in _WHISPER_FILES]
    tree[1]["lfs"] = {"size": 7, "oid": _LFS_OID}
    _fake_hf_apis(monkeypatch, tree)
    written = _fake_download(monkeypatch)
    notifier = _Notifier()

    downloader._download_from(
        "hf_mirror", spec.repo_id, spec, tmp_path, _EPS, notifier, threading.Event()  # type: ignore[arg-type]
    )

    cache = tmp_path / spec.placement / "models--Systran--faster-whisper-base"
    snapshot = cache / "snapshots" / _SHA
    assert sorted(p.name for p in snapshot.iterdir()) == sorted(_WHISPER_FILES)
    assert (cache / "refs" / "main").read_text(encoding="utf-8") == _SHA
    manifest = json.loads((cache / "trees" / f"{_SHA}.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in manifest} == set(_WHISPER_FILES)
    assert next(e for e in manifest if e["path"] == "model.bin")["sha256"] == _LFS_OID
    # 落盘后对账用的 sha256 真传给了下载原语
    assert len(written) == len(_WHISPER_FILES)


def test_download_from_degrades_to_main_and_tells_the_truth(
    tmp_path: Path, monkeypatch
) -> None:
    """解析不到提交号：按 snapshots/main 落盘、不写 refs/trees，并 warn 播报退化。"""
    spec = _spec("faster-whisper-base")
    tree = [{"type": "file", "path": name, "size": 7} for name in _WHISPER_FILES]
    _fake_hf_apis(monkeypatch, tree, sha=None)
    _fake_download(monkeypatch)
    notifier = _Notifier()

    downloader._download_from(
        "hf_mirror", spec.repo_id, spec, tmp_path, _EPS, notifier, threading.Event()  # type: ignore[arg-type]
    )

    cache = tmp_path / spec.placement / "models--Systran--faster-whisper-base"
    assert (cache / "snapshots" / "main" / "model.bin").is_file()
    assert not (cache / "refs").exists()
    assert not (cache / "trees").exists()
    assert any(level == "warn" and "无从对账" in msg for level, msg in notifier.logs)


# ---------------------------------------------------------------- 就地迁移


def _legacy_cache(tmp_path: Path, spec, *, model: str = "base") -> Path:
    """历史下载器留下的形态：snapshots/main 四件套、无 refs、无 trees。"""
    cache = tmp_path / spec.placement / f"models--Systran--faster-whisper-{model}"
    snapshot = cache / "snapshots" / "main"
    snapshot.mkdir(parents=True)
    for name in _WHISPER_FILES:
        (snapshot / name).write_bytes(b"x" * 16)
    return cache


def test_relayout_migrates_legacy_main_snapshot(tmp_path: Path, monkeypatch) -> None:
    spec = _spec("faster-whisper-base")
    cache = _legacy_cache(tmp_path, spec)
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: _SHA)

    result = downloader.relayout_whisper_cache(spec, tmp_path, _EPS)

    assert result["migrated"] is True
    target = Path(str(result["path"]))
    assert target == cache / "snapshots" / _SHA
    assert not (cache / "snapshots" / "main").exists()
    assert (cache / "refs" / "main").read_text(encoding="utf-8") == _SHA
    manifest = json.loads((cache / "trees" / f"{_SHA}.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in manifest} == set(_WHISPER_FILES)
    assert all(len(entry["sha256"]) == 64 for entry in manifest)
    # 幂等：已是目标布局就直接返回，不再触网
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: None)
    noop = downloader.relayout_whisper_cache(spec, tmp_path, _EPS)
    assert noop == {"path": str(target), "migrated": False}


def test_relayout_refuses_to_fabricate_a_revision(tmp_path: Path, monkeypatch) -> None:
    """网络解析不到提交号：如实报错，不造假提交号、不动盘上文件。"""
    spec = _spec("faster-whisper-base")
    cache = _legacy_cache(tmp_path, spec)
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: None)

    with pytest.raises(ValueError, match="解析不到提交号"):
        downloader.relayout_whisper_cache(spec, tmp_path, _EPS)
    assert (cache / "snapshots" / "main").is_dir()
    assert not (cache / "refs").exists()


def test_relayout_refuses_to_merge_two_revisions(tmp_path: Path, monkeypatch) -> None:
    spec = _spec("faster-whisper-base")
    cache = _legacy_cache(tmp_path, spec)
    (cache / "snapshots" / _SHA).mkdir(parents=True)
    monkeypatch.setattr(downloader, "resolve_revision", lambda *_a, **_k: _SHA)

    with pytest.raises(ValueError, match="人工裁决"):
        downloader.relayout_whisper_cache(spec, tmp_path, _EPS)


def test_relayout_rejects_non_whisper_and_missing_cache(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不是 whisper 系"):
        downloader.relayout_whisper_cache(_spec("kokoro-82m"), tmp_path, _EPS)
    with pytest.raises(ValueError, match="没有 whisper 缓存目录"):
        downloader.relayout_whisper_cache(_spec("faster-whisper-base"), tmp_path, _EPS)
