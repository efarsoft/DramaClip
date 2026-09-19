"""资产校验：引擎接入态从工厂派生，完整性判据按引擎各自的必需文件与缓存形态。

真实依据（2026-09-19 在 data/models 上量到，本机就是这些形状）：
  · ``asr/faster-whisper/models--Systran--faster-whisper-medium`` 的快照目录名是字面量
    ``main``、``refs/main`` 只有 4 字节，且没有 ``trees/``；根目录那份是 40 位提交号 + 40 字节 ref。
  · ``…faster-whisper-small/blobs/`` 里躺着 201MB 的 ``*.incomplete`` 半截文件。
  · medium 在 ``models/`` 根与 ``models/asr/faster-whisper/`` 下各有一份。
  · sherpa 的模型在 ``models/sherpa-onnx/melo/…``，而 ``tts/factory.py`` 读的是
    ``models/tts/sherpa-onnx/melo/…``——两边都不是登记路径。
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


# ---------------------------------------------------------------- 引擎接入态


def test_engine_ready_is_true_only_for_engines_the_factory_can_build() -> None:
    from dramaclip.engines.tts.factory import supported as tts_supported

    assert registry.engine_ready(_spec("kokoro-82m")) is True
    assert registry.engine_ready(_spec("indextts2")) is False
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


def test_verify_rejects_unresolved_snapshot_dir(tmp_path: Path) -> None:
    """snapshots/main + 4 字节 refs/main：下载没走到提交号就收工，正是本机 medium 的形状。"""
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    _whisper_cache(base, rev="main")
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    failing = {c["name"] for c in report["checks"] if c["status"] == "fail"}
    assert "快照提交号" in failing


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
    # 反向确认判据没被削平：那只盯着 small 的体检必须报出来。
    small = next(s for s in builtin_specs() if s.model_id == "faster-whisper-small")
    assert next(c for c in registry.verify(tmp_path / "models", small)["checks"]
                if c["name"] == "中断残留")["status"] == "fail"


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
    spec = _spec("faster-whisper-medium")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    cache = _whisper_cache(base)
    (cache / "blobs").mkdir()
    (cache / "blobs" / ("a" * 64 + ".incomplete")).write_bytes(b"x" * 1024)
    report = registry.verify(tmp_path / "models", spec)
    residue = next(c for c in report["checks"] if c["name"] == "中断残留")
    assert residue["status"] == "fail"
    assert "1" in residue["detail"]
    assert report["ok"] is False


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


def test_verify_sherpa_needs_its_dict_directory(tmp_path: Path) -> None:
    spec = _spec("sherpa-melo-zh")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
        (base / name).write_bytes(b"x" * 16)
    report = registry.verify(tmp_path / "models", spec)
    assert report["ok"] is False
    assert "dict" in next(c for c in report["checks"] if c["name"] == "必需文件")["detail"]


def test_sherpa_model_is_a_registered_asset(tmp_path: Path) -> None:
    """sherpa 在工厂里可选、引擎已接入，却在清单里没有登记项——所以它永远显示不了安装态。"""
    spec = _spec("sherpa-melo-zh")
    assert spec.kind == "tts"
    assert spec.engine == "sherpa_melo"
    assert registry.engine_ready(spec) is True
    # 登记路径必须与工厂实际加载的路径一致，否则「已装」和「能跑」会分家。
    from dramaclip.engines.tts.factory import model_dir

    assert model_dir(tmp_path / "models") == tmp_path / "models" / spec.placement


def test_kokoro_placement_and_factory_path_agree(tmp_path: Path) -> None:
    from dramaclip.engines.tts.factory import model_dir

    assert model_dir(tmp_path / "models", engine="kokoro") == (
        tmp_path / "models" / _spec("kokoro-82m").placement / "Kokoro-82M-v1.1-zh"
    )
