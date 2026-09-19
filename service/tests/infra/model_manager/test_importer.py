"""importer.inspect：导入向导第 ② 步的唯一判据——「这个目录是不是一份完整可用的资产」。

为什么不能拿 detect_status 用：它的判据是「placement 下存在一个权重文件」，半截目录一样过
（真机事故：faster-whisper-medium 缺 refs/main 被当成已装，10 集分析白跑）。导入是坏资产
进库前的最后一道闸，所以这里的每一项都必须是实测：文件在不在、权重多大、目标盘还剩多少。

识别只承认两种证据：HF 缓存目录名（models--org--name）与引擎各自的必需文件集。认不出来
就报「未识别」，绝不猜一个模型名把业主骗过第 ③ 步。
"""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra.model_manager import importer, registry

SNAPSHOT = "0123456789abcdef0123456789abcdef01234567"
# faster-whisper-medium 的标称 ~1.5GB：用稀疏文件称出这个数，落盘只占几簇。
MEDIUM_BYTES = int(1.5 * 1024**3)
_USAGE = namedtuple("usage", ("total", "used", "free"))


@pytest.fixture(autouse=True)
def steady_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「目标盘余量」钉成常量：这些用例测的是判据，不是本机此刻剩多少空间。"""
    monkeypatch.setattr(importer.shutil, "disk_usage", lambda _p: _USAGE(1024**4, 0, 500 * 1024**3))


def _write(path: Path, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _sparse(path: Path, nbytes: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0")
    with path.open("r+b") as handle:
        handle.truncate(nbytes)
    return path


def _whisper_files(root: Path, weight_bytes: int = MEDIUM_BYTES) -> None:
    """一份「齐全」的快照内容：必需文件按 registry 的判据来，一项不多一项不少。"""
    for name in registry.requirements("faster_whisper"):
        path = root / name
        if name == "model.bin":
            _sparse(path, weight_bytes)
        else:
            _write(path, b"meta")


def _cache_dir(
    base: Path,
    repo_dir: str = "models--Systran--faster-whisper-medium",
    weight_bytes: int = MEDIUM_BYTES,
) -> Path:
    cache = base / repo_dir
    snapshot = cache / "snapshots" / SNAPSHOT
    _whisper_files(snapshot, weight_bytes)
    _write(cache / "refs" / "main", SNAPSHOT.encode())
    _write(cache / "trees" / f"{SNAPSHOT}.json", b'{"files":[]}')
    return cache


def _check(result: dict[str, Any], name: str) -> dict[str, str]:
    hits = [item for item in result["checks"] if item["name"] == name]
    assert len(hits) == 1, f"检查项 {name} 应当恰好一条，实得 {len(hits)}"
    return hits[0]


def test_inspect_recognizes_a_complete_whisper_cache(tmp_path: Path) -> None:
    source = _cache_dir(tmp_path / "下载")

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is True
    assert result["model_id"] == "faster-whisper-medium"
    assert result["engine"] == "faster_whisper"
    assert result["kind"] == "asr"
    assert result["engine_ready"] is True
    assert result["basis"] != ""
    assert result["ok"] is True, result["checks"]


def test_inspect_pinpoints_the_unit_that_has_to_be_landed(tmp_path: Path) -> None:
    """第 ③ 步按这两个字段决定「搬哪一层」：缓存模型搬整份缓存，平铺目录搬它的内容。

    为什么单独钉：``str(None)`` 是 ``"None"``——一个字符串化的空值会让落位把目录搬进
    名叫 ``None`` 的抽屉里，而体检环节根本看不出这件事。
    """
    cache = _cache_dir(tmp_path / "下载")
    flat = tmp_path / "faster-whisper-medium"
    _whisper_files(flat)
    library = tmp_path / "library"

    by_cache = importer.inspect(library, cache)
    by_flat = importer.inspect(library, flat)

    assert Path(by_cache["cache_path"]) == cache
    assert Path(by_cache["model_root"]) == cache / "snapshots" / SNAPSHOT
    assert by_flat["cache_path"] is None
    assert Path(by_flat["model_root"]) == flat


def test_inspect_recognizes_a_flat_directory_by_its_files_and_name(tmp_path: Path) -> None:
    """业主从网盘下回来的常常是解好开的平铺目录，不是 HF 缓存骨架。"""
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source)

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is True
    assert result["model_id"] == "faster-whisper-medium"
    assert _check(result, "必需文件")["status"] == "pass"


def test_inspect_recognizes_a_release_folder_nested_one_level_down(tmp_path: Path) -> None:
    """zip 解出来常带一层同名目录：模型在里面，不在业主点的那一层。"""
    source = tmp_path / "sherpa-download"
    inner = source / "vits-melo-tts-zh_en"
    for name in registry.requirements("sherpa_melo"):
        path = inner / name
        if name == "dict":
            path.mkdir(parents=True, exist_ok=True)
        elif name == "model.onnx":
            _sparse(path, 200 * 1024 * 1024)
        else:
            _write(path, b"data")

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is True
    assert result["model_id"] == "sherpa-melo-zh"
    assert result["engine"] == "sherpa_melo"
    assert Path(result["model_root"]) == inner


def test_inspect_lists_every_missing_required_file_and_refuses(tmp_path: Path) -> None:
    """缺 tokenizer.json 的目录必须停在第 ② 步——这正是验收标准那一条。"""
    source = tmp_path / "faster-whisper-medium"
    _write(source / "config.json")
    _sparse(source / "model.bin", MEDIUM_BYTES)

    result = importer.inspect(tmp_path / "library", source)

    check = _check(result, "必需文件")
    assert check["status"] == "fail"
    assert "tokenizer.json" in check["detail"]
    assert "vocabulary.txt" in check["detail"]
    assert sorted(result["missing_files"]) == ["tokenizer.json", "vocabulary.txt"]
    assert result["ok"] is False


def test_inspect_measures_the_weight_against_the_nominated_size(tmp_path: Path) -> None:
    """标称 ~1.5GB 而实得 2KB：下载中断的形态，尺寸对账必须说出口。"""
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source, weight_bytes=2048)

    result = importer.inspect(tmp_path / "library", source)

    check = _check(result, "权重尺寸对账")
    assert check["status"] == "fail"
    assert "1.5GB" in check["detail"]  # 标称值原样摆出来，业主才知道差多少
    assert result["ok"] is False


def test_inspect_accepts_a_weight_within_the_nominated_budget(tmp_path: Path) -> None:
    cache = _cache_dir(tmp_path / "下载", weight_bytes=int(0.95 * MEDIUM_BYTES))

    result = importer.inspect(tmp_path / "library", cache)

    assert _check(result, "权重尺寸对账")["status"] == "pass"
    assert result["ok"] is True


def test_inspect_refuses_a_flat_whisper_dir_that_the_engine_cannot_load(tmp_path: Path) -> None:
    """文件齐了也没用：faster-whisper 按 HF 缓存寻址，平铺目录引擎读不到。"""
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source)

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is True
    assert _check(result, "必需文件")["status"] == "pass"
    assert "缓存" in _check(result, "缓存布局")["detail"]
    assert result["ok"] is False


def test_inspect_flags_leftover_incomplete_downloads(tmp_path: Path) -> None:
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source)
    _write(source / "blobs" / "part.incomplete", b"junk")

    result = importer.inspect(tmp_path / "library", source)

    assert _check(result, "中断残留")["status"] == "fail"
    assert result["ok"] is False


def test_inspect_declares_an_unmatched_directory_unrecognized(tmp_path: Path) -> None:
    """认不出来就直说：猜个模型名等于把业主的目录登记成别的东西。"""
    source = tmp_path / "misc-stuff"
    _write(source / "readme.md", b"hello")
    _sparse(source / "whatever.safetensors", 3000)

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is False
    assert result["model_id"] is None
    assert "未匹配" in result["basis"]
    assert _check(result, "必需文件")["status"] == "fail"
    assert _check(result, "引擎接入")["status"] == "skip"


def test_inspect_rejects_an_empty_directory(tmp_path: Path) -> None:
    source = tmp_path / "nothing-here"
    source.mkdir()

    result = importer.inspect(tmp_path / "library", source)

    assert result["recognized"] is False
    assert result["file_count"] == 0
    assert _check(result, "目录内容")["status"] == "fail"


def test_inspect_measures_bytes_and_target_free_space(tmp_path: Path) -> None:
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source, weight_bytes=4096)
    library = tmp_path / "library"
    (library / "asr").mkdir(parents=True)

    result = importer.inspect(library, source)

    assert result["file_count"] == 4
    assert result["total_bytes"] == 4096 + 3 * 4  # model.bin + 三个 meta 小文件
    assert result["target"]["placement"] == "asr/faster-whisper"
    assert result["target"]["free_bytes"] > 0
    assert _check(result, "磁盘可容纳")["status"] == "pass"


def test_inspect_says_the_disk_is_too_small(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "faster-whisper-medium"
    _whisper_files(source, weight_bytes=4096)
    usage = _USAGE(0, 0, 10)
    monkeypatch.setattr(importer.shutil, "disk_usage", lambda _p: usage)

    result = importer.inspect(tmp_path / "library", source)

    assert _check(result, "磁盘可容纳")["status"] == "fail"
    assert result["ok"] is False


def test_inspect_surfaces_an_existing_asset_as_a_conflict(tmp_path: Path) -> None:
    library = tmp_path / "library"
    _cache_dir(library / "asr" / "faster-whisper")
    source = _cache_dir(tmp_path / "下载")

    result = importer.inspect(library, source)

    conflict = result["conflict"]
    assert conflict is not None
    assert conflict["model_id"] == "faster-whisper-medium"
    assert Path(conflict["path"]).is_dir()
    assert conflict["size_bytes"] > 0


def test_inspect_refuses_a_source_inside_the_library(tmp_path: Path) -> None:
    """库里挑出来的目录当来源 = 把自己拷给自己，覆盖时还会把原件一起改名。"""
    library = tmp_path / "library"
    source = _cache_dir(library / "asr" / "faster-whisper")

    with pytest.raises(ValueError, match="模型目录内"):
        importer.inspect(library, source)


def test_inspect_refuses_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        importer.inspect(tmp_path / "library", tmp_path / "nope")


def test_requirements_accessor_shares_one_table_with_verify() -> None:
    """导入与体检共用一份必需文件集：判据只存在于 registry._REQUIREMENTS 一处。"""
    assert registry.requirements("faster_whisper") == registry._REQUIREMENTS["faster_whisper"]
    assert registry.requirements("no-such-engine") == ()
