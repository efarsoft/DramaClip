"""registry v2：档位/评级元数据 + 状态探测。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.model_manager import registry
from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs


def test_catalog_has_tier_metadata() -> None:
    specs = {spec.model_id: spec for spec in builtin_specs()}
    assert specs["faster-whisper-base"].tier == "fast"
    assert specs["faster-whisper-small"].tier == "balanced"
    assert specs["faster-whisper-large-v3"].tier == "accurate"
    assert all(1 <= spec.speed <= 5 for spec in specs.values())
    assert all(1 <= spec.quality <= 5 for spec in specs.values())


def test_detect_status_not_installed(tmp_path: Path) -> None:
    spec = builtin_specs()[0]
    status = registry.detect_status(tmp_path / "models", spec)
    assert status["status"] == "not_installed"
    assert status["size_label"] != ""
    assert status["tier"] != ""


def test_detect_status_installed_via_weights(tmp_path: Path) -> None:
    spec = next(s for s in builtin_specs() if s.model_id == "kokoro-82m")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    (base / "model.pth").write_bytes(b"x")
    status = registry.detect_status(tmp_path / "models", spec)
    assert status["status"] == "installed"


def test_find_returns_none_when_missing(tmp_path: Path) -> None:
    spec = builtin_specs()[0]
    assert registry.find(spec, tmp_path / "models") is None


def test_dropped_engine_keeps_no_catalog_row() -> None:
    """撤下的引擎不能留一行在清单里：留了就是资产库上一行永远点不动下载的「缺模型」。"""
    assert [spec.model_id for spec in builtin_specs() if spec.engine == "sherpa_melo"] == []


def test_requirements_table_has_no_row_for_a_gone_engine() -> None:
    """体检判据表必须与「工厂真能加载本地模型」的引擎一一对应。

    撤引擎时漏删这里一行：那行永远匹配不到任何资产，是死配置。
    加引擎时漏配这里一行：``requirements()`` 对查不到的引擎交空表，体检的
    「必需文件」一项就没有东西可查——零判据等于永远通过，就绪成了白送的。
    """
    from dramaclip.engines.analysis.runtime import supported as asr_supported
    from dramaclip.engines.tts.factory import _MODEL_DIRS

    local_tts = {engine for engine, relative in _MODEL_DIRS.items() if relative is not None}
    assert set(registry._REQUIREMENTS) == set(asr_supported()) | local_tts


def test_a_source_less_spec_offers_no_download_source() -> None:
    """空 ``repo_id`` 的登记项必须交出空表：让调用方明确拒绝，而不是拼个不存在的 URL。

    清单里如今没有这种行（原先是 sherpa-melo-zh），所以判据按类型本身验，
    等下一只「只能手工导入」的资产登记进来时它照得住。
    """
    spec = ModelSpec(
        model_id="manual-only",
        kind="tts",
        engine="kokoro",
        repo_id="",
        placement="tts/manual-only",
        name="只能手工导入的模型",
    )
    assert spec.sources() == []

