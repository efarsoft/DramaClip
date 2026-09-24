"""ASR 引擎选择的分派面：`supported()` 与工厂分支必须同源，未知引擎显式拒绝。

守卫口径：接进工厂的引擎才许构建；没接的（如已移除的 firedred）必须显式拒绝并报出
可用引擎——不许 ImportError，更不许静默回退（业主以为在用 A，实际被换了 B）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis import runtime
from dramaclip.engines.analysis.transcriber import (
    FasterWhisperEngine,
    ParaformerEngine,
    SenseVoiceEngine,
)
from dramaclip.infra import config
from dramaclip.infra.model_manager import registry
from dramaclip.infra.model_manager.registry import builtin_specs

# 名单的第二份抄本，故意抄在测试里：supported() 少一个/多一个都会在这里撞车。
_BUILDS: dict[str, type] = {
    "faster_whisper": FasterWhisperEngine,
    "sensevoice": SenseVoiceEngine,
    "paraformer": ParaformerEngine,
}


def _settings(**overrides: str) -> config.Settings:
    return {**config.DEFAULTS, **overrides}


def test_every_supported_engine_builds_without_loading_a_model(tmp_path: Path) -> None:
    assert runtime.supported() == frozenset(_BUILDS)
    for engine, cls in _BUILDS.items():
        built = runtime._build_transcriber(_settings(**{"asr.engine": engine}), tmp_path)
        assert type(built) is cls


def test_unknown_engine_is_rejected_instead_of_silently_falling_back(
    tmp_path: Path,
) -> None:
    """firedred 已从清单移除、工厂里也没有：必须拒绝，且告诉业主可用的是谁。"""
    with pytest.raises(ValueError, match="未知 ASR 引擎: firedred"):
        runtime._build_transcriber(_settings(**{"asr.engine": "firedred"}), tmp_path)


def test_no_registry_entry_builds_unless_engine_ready(tmp_path: Path) -> None:
    """清单里每个 asr 项：要么工厂能建，要么 engine_ready 为 false——不得两头都不成立。"""
    for spec in (s for s in builtin_specs() if s.kind == "asr"):
        if registry.engine_ready(spec):
            built = runtime._build_transcriber(_settings(**{"asr.engine": spec.engine}), tmp_path)
            assert type(built) is _BUILDS[spec.engine]
        else:
            with pytest.raises(ValueError):
                runtime._build_transcriber(_settings(**{"asr.engine": spec.engine}), tmp_path)


def test_engine_path_matches_the_registry_placement(tmp_path: Path) -> None:
    """funasr 两引擎自己拼的路径必须等于清单里的 placement，否则探测与加载会各读一份。"""
    models_dir = tmp_path / "models"
    for engine, cls in (("sensevoice", SenseVoiceEngine), ("paraformer", ParaformerEngine)):
        spec = next(s for s in builtin_specs() if s.engine == engine)
        engine_obj = cls(models_dir=models_dir)  # type: ignore[call-arg]
        assert engine_obj._model_dir == models_dir / spec.placement  # type: ignore[attr-defined]


def test_compute_type_setting_reaches_the_engine(tmp_path: Path) -> None:
    """接线验收：asr.compute_type 里写的档位必须原样到引擎手里——传没传得到，比传什么更先要命。

    反面即死设置：DEFAULTS 里写着、构造时没人传，GPU 白白闲置。
    """
    engine = runtime._build_transcriber(_settings(**{"asr.compute_type": "float16"}), tmp_path)
    assert isinstance(engine, FasterWhisperEngine)
    assert engine._compute_type == "float16"
    default = runtime._build_transcriber(_settings(), tmp_path)
    assert isinstance(default, FasterWhisperEngine)
    assert default._compute_type == config.DEFAULTS["asr.compute_type"]
