"""importer.commit：第 ③ 步的落位执行——复制 / 移动 / 仅登记，三种冲突裁决。

这一段会动业主磁盘上的真文件，所以规矩只有一条：**没得到明确裁决就不动原来的东西**。
覆盖不删除而是改名留后路，移动只在落位体检通过后才清源，未识别的目录不允许猜 placement。

体积对账的判据本身在 test_importer.py 里钉死；这里把标称值钉成 4KB——稀疏文件一旦被
真复制就变成 1.5GB 实打实落盘，八个用例能写十几个 GB，测的却是目录搬移。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.infra.model_manager import importer

SNAPSHOT = "0123456789abcdef0123456789abcdef01234567"
CACHE_NAME = "models--Systran--faster-whisper-medium"
WEIGHT = b"m" * 4096


def _write(path: Path, payload: bytes = b"meta") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _cache_dir(base: Path) -> Path:
    cache = base / CACHE_NAME
    snapshot = cache / "snapshots" / SNAPSHOT
    for name in ("config.json", "tokenizer.json", "vocabulary.txt"):
        _write(snapshot / name)
    _write(snapshot / "model.bin", WEIGHT)
    _write(cache / "refs" / "main", SNAPSHOT.encode())
    _write(cache / "trees" / f"{SNAPSHOT}.json", b'{"files":[]}')
    return cache


@pytest.fixture(autouse=True)
def small_nominal_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, "_nominal_bytes", lambda _label: len(WEIGHT))


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / "asr" / "faster-whisper").mkdir(parents=True)
    return root


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _cache_dir(tmp_path / "下载")


def _flat_dir(base: Path, *, complete: bool = False) -> Path:
    """平铺的 faster-whisper 目录：引擎按 HF 缓存寻址，读不到它——用来造「体检不通过」。"""
    root = base / "faster-whisper-medium"
    _write(root / "config.json")
    _write(root / "model.bin", WEIGHT)
    if complete:
        _write(root / "tokenizer.json")
        _write(root / "vocabulary.txt")
    return root


def _measure(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def test_commit_copy_lands_in_the_canonical_placement_and_verifies(
    library: Path, source: Path
) -> None:
    """复制落位后必须能被库自己认出来：placement 就位 + 体检复跑通过。"""
    result = importer.commit(library, source, mode="copy")

    placed = Path(result["path"])
    assert placed.parent == library / "asr" / "faster-whisper"
    assert placed.name == CACHE_NAME
    # 临时目录是落位过程的中间态，不该在库里留下来占位（它会被下一个模型的冲突判断看见）
    assert sorted(path.name for path in placed.parent.iterdir()) == [CACHE_NAME]
    assert (placed / "snapshots" / SNAPSHOT / "model.bin").read_bytes() == WEIGHT
    assert result["post"]["ok"] is True, result["post"]["checks"]
    assert result["bytes_moved"] == _measure(source)
    assert source.is_dir(), "复制不清原处"


def test_commit_records_the_asset_as_locally_imported(library: Path, source: Path) -> None:
    """「本地导入」与「应用下载」要分得开：移除时才敢问要不要连源目录一起删。"""
    importer.commit(library, source, mode="copy")

    record = importer.records(library)[0]
    assert record["model_id"] == "faster-whisper-medium"
    assert record["mode"] == "copy"
    assert record["source_path"] == str(source)


def test_commit_copy_reports_progress_in_bytes(library: Path, source: Path) -> None:
    seen: list[tuple[int, int]] = []

    importer.commit(
        library, source, mode="copy", on_progress=lambda done, total: seen.append((done, total))
    )

    assert seen, "GB 级复制必须回报进度，否则业主只能盯着转圈"
    assert seen[-1] == (_measure(source), _measure(source))
    assert [done for done, _total in seen] == sorted(done for done, _total in seen)


def test_commit_refuses_to_land_an_asset_that_failed_the_check(
    library: Path, tmp_path: Path
) -> None:
    """第 ② 步没过就不许进第 ③ 步——闸门在服务端，不只在按钮上。"""
    with pytest.raises(ValueError, match="体检"):
        importer.commit(library, _flat_dir(tmp_path), mode="copy")

    assert list((library / "asr" / "faster-whisper").iterdir()) == []


def test_commit_copy_of_an_incomplete_asset_needs_an_explicit_ruling(
    library: Path, tmp_path: Path
) -> None:
    """业主显式选了「不完整导入」才放行，且报告里必须仍然写着不通过。"""
    result = importer.commit(library, _flat_dir(tmp_path), mode="copy", allow_incomplete=True)

    assert Path(result["path"]).is_dir()
    assert result["incomplete"] is True
    assert result["post"]["ok"] is False


def test_commit_move_clears_the_source_only_after_a_verified_landing(
    library: Path, source: Path
) -> None:
    result = importer.commit(library, source, mode="move")

    assert result["post"]["ok"] is True
    assert not source.exists(), "落位体检通过后才清源"
    assert Path(result["path"]).is_dir()


def test_commit_move_of_an_incomplete_asset_leaves_the_source_alone(
    library: Path, tmp_path: Path
) -> None:
    """不完整导入 + 移动：源目录可能是业主唯一的副本，绝不替他删东西。"""
    flat = _flat_dir(tmp_path, complete=True)

    result = importer.commit(library, flat, mode="move", allow_incomplete=True)

    assert result["post"]["ok"] is False
    assert flat.is_dir()


def test_commit_needs_a_conflict_ruling_before_touching_an_installed_asset(
    library: Path, source: Path
) -> None:
    _cache_dir(library / "asr" / "faster-whisper")

    with pytest.raises(ValueError, match="冲突"):
        importer.commit(library, source, mode="copy")


def test_commit_overwrite_renames_the_previous_asset_instead_of_deleting_it(
    library: Path, source: Path
) -> None:
    old = _cache_dir(library / "asr" / "faster-whisper")
    (old / "snapshots" / SNAPSHOT / "tokenizer.json").unlink()  # 库里那份是坏的

    result = importer.commit(library, source, mode="copy", on_conflict="overwrite")

    backups = sorted((library / "asr" / "faster-whisper").glob("models--*_backup_*"))
    assert len(backups) == 1
    assert (backups[0] / "snapshots" / SNAPSHOT / "config.json").is_file(), "旧文件一份都不能少"
    assert result["conflict_action"] == "backup"
    assert result["post"]["ok"] is True, result["post"]["checks"]


def test_commit_merge_adds_only_what_the_library_is_missing(library: Path, source: Path) -> None:
    old = _cache_dir(library / "asr" / "faster-whisper")
    keeper = old / "snapshots" / SNAPSHOT / "model.bin"
    keeper.write_bytes(b"z" * len(WEIGHT))  # 业主自己那份权重，内容一眼可辨
    (old / "snapshots" / SNAPSHOT / "vocabulary.txt").unlink()

    result = importer.commit(library, source, mode="copy", on_conflict="merge")

    assert keeper.read_bytes() == b"z" * len(WEIGHT), "合并不许动业主已有的权重"
    assert (old / "snapshots" / SNAPSHOT / "vocabulary.txt").read_bytes() == b"meta"
    assert result["conflict_action"] == "merge"
    assert result["post"]["ok"] is True, result["post"]["checks"]


def test_commit_coexist_registers_without_touching_the_library(library: Path, source: Path) -> None:
    _cache_dir(library / "asr" / "faster-whisper")

    result = importer.commit(library, source, mode="copy", on_conflict="coexist")

    assert result["external"] is True
    assert result["path"] == str(source)
    assert [record["path"] for record in importer.records(library)] == [str(source)]
    assert [record["source_path"] for record in importer.records(library)] == [str(source)], (
        "「来源」必须是业主挑的那个目录：写成库内 placement，移除时的提示就指向错了地方"
    )
    # 并存一个字节都没搬进库：登记里写 copy，资产行的「删除」提示就会说错话。
    assert [record["mode"] for record in importer.records(library)] == ["register"]
    assert result["conflict_action"] == "coexist"


def test_commit_coexist_of_an_incomplete_asset_stays_flagged(
    library: Path, tmp_path: Path
) -> None:
    """业主明知不完整还要并存：登记本里那条必须继续带着这个印记。"""
    _cache_dir(library / "asr" / "faster-whisper")

    result = importer.commit(
        library, _flat_dir(tmp_path / "下载"), mode="copy", on_conflict="coexist",
        allow_incomplete=True,
    )

    assert result["incomplete"] is True
    assert [record["incomplete"] for record in importer.records(library)] == [True]


def test_commit_register_copies_nothing(library: Path, source: Path) -> None:
    result = importer.commit(library, source, mode="register")

    assert result["path"] == str(source)
    assert result["bytes_moved"] == 0
    assert not (library / "asr" / "faster-whisper" / CACHE_NAME).exists()
    assert [record["mode"] for record in importer.records(library)] == ["register"]


def test_commit_registers_an_unrecognized_directory_as_an_external_asset(
    library: Path, tmp_path: Path
) -> None:
    """认不出来的目录只能登记成外部资产：没有 model_id，也就没有「选为生效」。"""
    given = tmp_path / "同事给的模型"
    _write(given / "whatever.safetensors", b"s" * 2048)

    result = importer.commit(
        library, given, mode="register", external_kind="tts", label="同事的音色"
    )

    assert result["external"] is True
    assert result["model_id"] is None
    record = importer.records(library)[0]
    assert record["kind"] == "tts"
    assert record["label"] == "同事的音色"


def test_commit_refuses_external_registration_without_a_capability(
    library: Path, tmp_path: Path
) -> None:
    given = tmp_path / "同事给的模型"
    _write(given / "whatever.safetensors", b"s" * 2048)

    with pytest.raises(ValueError, match="能力"):
        importer.commit(library, given, mode="register")


def test_commit_refuses_to_guess_a_placement_for_an_unrecognized_directory(
    library: Path, tmp_path: Path
) -> None:
    """未识别 = 不知道该放哪；猜一个 placement 就是把资产丢进黑洞。

    ``external_kind`` 给足：不然「必须指定能力」那道闸会替 placement 闸挡下用例，
    这条断言就什么都没钉住。
    """
    given = tmp_path / "同事给的模型"
    _write(given / "whatever.safetensors", b"s" * 2048)

    with pytest.raises(ValueError, match="placement"):
        importer.commit(library, given, mode="copy", external_kind="tts")


def test_commit_rejects_an_unknown_mode(library: Path, source: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        importer.commit(library, source, mode="teleport")


def test_records_are_empty_without_a_manifest(tmp_path: Path) -> None:
    assert importer.records(tmp_path / "library") == []


def test_records_survive_a_corrupt_manifest_without_bricking_the_library(tmp_path: Path) -> None:
    """登记本坏了不能把整个资产库一起带崩——但也不能装作没坏。"""
    library = tmp_path / "library"
    library.mkdir()
    importer.manifest_path(library).write_text("{不是 json", encoding="utf-8")

    assert importer.records(library) == []
    assert importer.records_error(library) != ""


def test_re_registering_the_same_path_updates_the_record(library: Path, source: Path) -> None:
    importer.commit(library, source, mode="register")
    importer.commit(library, source, mode="register", label="同一份，改了个名字")

    records = importer.records(library)
    assert len(records) == 1
    assert records[0]["label"] == "同一份，改了个名字"


def test_forget_drops_exactly_the_record_it_was_asked_to_drop(
    library: Path, source: Path, tmp_path: Path
) -> None:
    """另一条登记必须留着：断言写成「清空后为空」的话，乱删也能过。"""
    other = _cache_dir(tmp_path / "另一个下载")
    importer.commit(library, source, mode="register")
    importer.commit(library, other, mode="register")

    importer.forget(library, source)

    assert [record["path"] for record in importer.records(library)] == [str(other)]
