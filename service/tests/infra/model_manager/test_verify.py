"""资产校验：引擎接入态从工厂派生，完整性判据按引擎各自的必需文件与缓存形态。

真实依据（2026-09-19 在 data/models 上量到，本机就是这些形状）：
  · ``asr/faster-whisper/models--Systran--faster-whisper-medium`` 的快照目录名是字面量
    ``main``、``refs/main`` 只有 4 字节，且没有 ``trees/``；根目录那份是 40 位提交号 + 40 字节 ref。
  · ``…faster-whisper-small/blobs/`` 里躺着 201MB 的 ``*.incomplete`` 半截文件。
  · medium 在 ``models/`` 根与 ``models/asr/faster-whisper/`` 下各有一份。
  · sherpa 当年在 ``models/sherpa-onnx/melo/…``，而 ``tts/factory.py`` 读的是
    ``models/tts/sherpa-onnx/melo/…``——两边都不是登记路径（该引擎 2026-09-20 撤下；
    「登记路径 = 工厂加载路径」这条判据现在由下面的 kokoro 对账用例守着）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from dramaclip.infra.model_manager import registry
from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs

_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
_REV = "536b0662742c02347bc0e980a01041f333bce120"


def _spec(model_id: str) -> ModelSpec:
    return next(s for s in builtin_specs() if s.model_id == model_id)


def _whisper_cache(base: Path, *, model: str = "medium", rev: str = _REV) -> Path:
    """按 HF hub 缓存布局搭一份形态正确的 whisper 目录，返回缓存根。"""
    cache = base / f"models--Systran--faster-whisper-{model}"
    snapshot = cache / "snapshots" / rev
    snapshot.mkdir(parents=True)
    (cache / "refs").mkdir()
    (cache / "refs" / "main").write_text(rev)
    (cache / "trees").mkdir()
    (cache / "trees" / f"{rev}.json").write_text("{}")
    for name in _WHISPER_FILES:
        (snapshot / name).write_bytes(b"x" * 16)
    return cache


def test_detect_status_reports_actual_bytes(tmp_path: Path) -> None:
    """就绪度条要说「占用 0.63GB」——那必须是磁盘实占，不是清单里写的标称大小。

    两者不是一回事：标称 ~350MB 的 Kokoro 加上缓存骨架与词典会超；而中断的下载
    只落了 192MB 半截文件，按标称报就把磁盘真实占用瞒过去了。
    """
    spec = _spec("sensevoice-small")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    (base / "model.pt").write_bytes(bytes(2048))
    (base / "jam" / "nested").mkdir(parents=True)
    (base / "jam" / "nested" / "extra.bin").write_bytes(bytes(1024))

    status = registry.detect_status(tmp_path / "models", spec)

    assert status["size_bytes"] == 3072
    # 未安装：没有目录可统计，报 0 而不是缺字段——前端不得拿 undefined 当 0。
    other = registry.detect_status(tmp_path / "models", _spec("kokoro-82m"))
    assert other["size_bytes"] == 0


def test_detect_status_whisper_size_covers_its_own_cache_only(tmp_path: Path) -> None:
    """四个 whisper 档位共用一个 placement 目录——体积必须按各自缓存目录切分。

    否则「small 占用」会把 medium/large 的几 GB 一并算进来。且要统计整个缓存根：
    HF 布局下权重实体落在 blobs/，``path`` 指向的 snapshots/<rev>/ 只是入口目录，
    只算它等于把真实磁盘占用漏掉。
    """
    models = tmp_path / "models"
    base = models / "asr/faster-whisper"
    small = _whisper_cache(base, model="small")
    (small / "blobs").mkdir()
    (small / "blobs" / "model.bin.incomplete").write_bytes(bytes(4096))
    # 邻居缓存：一字节都不该算进 small。
    _whisper_cache(base, model="medium")

    status = registry.detect_status(models, _spec("faster-whisper-small"))

    # 本缓存实占 = snapshots 4×16 + refs/main 40 + trees/<rev>.json 2 + blobs 4096
    assert status["size_bytes"] == 64 + 40 + 2 + 4096


# ---------------------------------------------------------------- 引擎接入态


def test_engine_ready_is_true_only_for_engines_the_factory_can_build() -> None:
    from dramaclip.engines.tts.factory import supported as tts_supported

    assert registry.engine_ready(_spec("kokoro-82m")) is True
    assert registry.engine_ready(_spec("indextts2")) is True, (
        "indextts2 已接进工厂（a88da7b），断言不得停留在接入前"
    )
    assert registry.engine_ready(_spec("vibevoice-1.5b")) is False
    # 防漂移：清单里出现过的 TTS 引擎，「已接入」必须等价于「工厂认得」，两边不得各存一份名单。
    listed = {s.engine for s in builtin_specs() if s.kind == "tts"}
    wired = {s.engine for s in builtin_specs() if s.kind == "tts" and registry.engine_ready(s)}
    assert wired == listed & set(tts_supported())


def test_engine_ready_asr_follows_the_analysis_runtime_dispatch() -> None:
    from dramaclip.engines.analysis.runtime import supported as asr_supported

    assert registry.engine_ready(_spec("faster-whisper-base")) is True
    assert registry.engine_ready(_spec("sensevoice-small")) is True
    assert registry.engine_ready(_spec("paraformer-large")) is False
    assert registry.engine_ready(_spec("firedred-asr-aed-l")) is False
    wired = {s.engine for s in builtin_specs() if s.kind == "asr" and registry.engine_ready(s)}
    assert wired == set(asr_supported())


def test_dead_paraformer_branch_is_gone_from_the_runtime() -> None:
    """paraformer 在 registry 里有登记项却没有任何实现，走它只会 ImportError。"""
    import inspect

    from dramaclip.engines.analysis import runtime

    assert "ParaformerEngine" not in inspect.getsource(runtime)


# ---------------------------------------------------------------- 完整性校验


def test_verify_accepts_a_well_formed_hf_cache(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    _whisper_cache(base)
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is True, report
    assert {c["name"] for c in report["checks"]} >= {"必需文件", "快照提交号", "下载清单"}


def test_degraded_main_snapshot_without_metadata_warns_but_stays_usable(tmp_path: Path) -> None:
    """规格 §10.1：目录名非提交号且无 refs/trees → warn「无从对账」，不 fail。

    snapshots/main 正是历史版本自家下载器落出的形态——无从对账 ≠ 权重缺损，
    能不能加载留给能力层自检，文件层不判死（本机 medium 曾被这条判据禁掉「选为生效」）。
    """
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base, rev="main")
    shutil.rmtree(cache / "trees")
    shutil.rmtree(cache / "refs")
    report = registry.verify(tmp_path / "models", spec)
    revision = next(c for c in report["checks"] if c["name"] == "快照提交号")
    assert revision["status"] == "warn"
    assert "无从" in revision["detail"]
    assert report["ok"] is True, report


def test_main_snapshot_with_trees_manifest_is_a_contradiction(tmp_path: Path) -> None:
    """有 trees 清单却配着非提交号的目录名：清单自称可对账，与目录名互相打脸 → fail。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    _whisper_cache(base, rev="main")
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    revision = next(c for c in report["checks"] if c["name"] == "快照提交号")
    assert revision["status"] == "fail"
    assert "互相矛盾" in revision["detail"]


def test_refs_pointing_elsewhere_still_fails(tmp_path: Path) -> None:
    """refs 与快照目录名两个权威意见不同是真矛盾，severity 重划不动这条 fail。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base, rev="main")
    (cache / "refs" / "main").write_text(_REV)
    report = registry.verify(tmp_path / "models", spec)
    revision = next(c for c in report["checks"] if c["name"] == "快照提交号")
    assert revision["status"] == "fail"
    assert "不一致" in revision["detail"]


def test_verify_handles_a_cache_with_no_snapshot_dir(tmp_path: Path) -> None:
    """只有 blobs/ 残骸、snapshots 空：体检要报「没有快照目录」，而不是自己抛异常。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    shutil.rmtree(cache / "snapshots")

    report = registry.verify(tmp_path / "models", spec)

    assert report["ok"] is False
    check = next(c for c in report["checks"] if c["name"] == "必需文件")
    assert check["status"] == "fail"
    assert "快照" in check["detail"]


def test_verify_rejects_a_dangling_ref(tmp_path: Path) -> None:
    """``refs/main`` 写着合法提交号却没有对应快照目录：退回目录序时两者对不上，即下载未收口。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "refs" / "main").write_text("0" * 40)

    report = registry.verify(tmp_path / "models", spec)

    assert report["ok"] is False
    check = next(c for c in report["checks"] if c["name"] == "快照提交号")
    assert check["status"] == "fail"
    assert "refs/main" in check["detail"], "得说清是 ref 与快照不一致，而不是泛泛的「不完整」"


def test_verify_tolerates_a_hand_placed_cache_without_manifest(tmp_path: Path) -> None:
    """手动放置的模型没有 ``trees/`` 清单：报 warn 让人知道无法逐文件对账，但不判死。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "trees" / f"{_REV}.json").unlink()

    report = registry.verify(tmp_path / "models", spec)

    assert report["ok"] is True, report
    warned = {c["name"] for c in report["checks"] if c["status"] == "warn"}
    assert warned == {"下载清单"}


def test_verify_residue_scopes_to_the_models_own_cache(tmp_path: Path) -> None:
    """同 placement 下**别的** whisper 模型下载中断，不能把本模型一并判死。

    真机形状：``asr/faster-whisper/`` 一个目录里躺着 base/small/medium 三份缓存，
    small 有 192MB 的 .incomplete，而 base/medium 是完整的——判据必须按模型切分，
    否则体检页会说「base 也不完整」，导入向导也会白拦一道。
    """
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    _whisper_cache(base)
    other = _whisper_cache(base, model="small")
    (other / "blobs").mkdir()
    (other / "blobs" / "model.binaaaaaaaa.incomplete").write_bytes(b"0")

    report = registry.verify(tmp_path / "models", spec)

    assert report["ok"] is True, report
    residue = next(c for c in report["checks"] if c["name"] == "中断残留")
    assert residue["status"] == "pass"
    # 反向确认判据没被削平：那只盯着 small 的体检必须报出来（§10.1 后是 warn，仍上卡）。
    small = next(s for s in builtin_specs() if s.model_id == "faster-whisper-small")
    small_residue = next(
        c for c in registry.verify(tmp_path / "models", small)["checks"] if c["name"] == "中断残留"
    )
    assert small_residue["status"] == "warn"


def test_verify_ignores_hf_lock_dirs_when_checking_duplicates(tmp_path: Path) -> None:
    """``models/.locks/models--…`` 是 hf_hub 的锁目录，不是第二份缓存。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (tmp_path / "models" / ".locks" / cache.name).mkdir(parents=True)

    report = registry.verify(tmp_path / "models", spec)

    warned = {c["name"] for c in report["checks"] if c["status"] == "warn"}
    assert "唯一路径" not in warned, report


def test_verify_reports_interrupted_download_residue(tmp_path: Path) -> None:
    """残留是卫生问题不是可用性缺陷（§10.1 fail→warn）：上卡、报体积、给出「可安全清理」。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "blobs").mkdir()
    (cache / "blobs" / ("a" * 64 + ".incomplete")).write_bytes(b"x" * 1024)
    report = registry.verify(tmp_path / "models", spec)
    residue = next(c for c in report["checks"] if c["name"] == "中断残留")
    assert residue["status"] == "warn"
    assert "1 个" in residue["detail"]
    assert "清理" in residue["detail"]
    assert report["ok"] is True, report


def test_verify_reports_the_same_model_cached_twice(tmp_path: Path) -> None:
    """根目录与登记路径各有一份：引擎只会用登记路径那份，另一份白占磁盘。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    _whisper_cache(base)
    _whisper_cache(tmp_path / "models")
    report = registry.verify(tmp_path / "models", spec)
    dup = next(c for c in report["checks"] if c["name"] == "唯一路径")
    assert dup["status"] == "warn"


def test_verify_fails_when_a_required_file_is_absent(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "snapshots" / _REV / "tokenizer.json").unlink()
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    assert next(c for c in report["checks"] if c["name"] == "必需文件")["status"] == "fail"


def test_verify_rejects_zero_byte_weights(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "snapshots" / _REV / "model.bin").write_bytes(b"")
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    assert next(c for c in report["checks"] if c["name"] == "权重非空")["status"] == "fail"


def test_verify_missing_model_reports_a_single_clear_failure(tmp_path: Path) -> None:
    spec = _spec("faster-whisper-medium")
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    assert report["checks"][0]["name"] == "目录存在"
    assert report["checks"][0]["status"] == "fail"


def test_kokoro_placement_and_factory_path_agree(tmp_path: Path) -> None:
    from dramaclip.engines.tts.factory import model_dir

    assert model_dir(tmp_path / "models", engine="kokoro") == (
        tmp_path / "models" / _spec("kokoro-82m").placement / "Kokoro-82M-v1.1-zh"
    )
