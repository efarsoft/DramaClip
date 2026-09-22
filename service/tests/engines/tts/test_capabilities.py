"""A3：TTS 引擎能力声明——caps 值必须来自引擎真实属性（量出来的，不许编）。

量到的事实（2026-09-22）：
  · edge-tts Communicate 签名含 rate 参数（实测 inspect.signature）→ speed native；
    输出 audio-24khz-48kbitrate-mono-mp3（edge_tts/communicate.py 源码）→ 24000Hz。
  · kokoro KPipeline.__call__ 签名含 speed 参数 → native；_SAMPLE_RATE=24000。
  · indextts2 隔离 venv 实测 IndexTTS2.infer 签名：duration_factor（→native）、
    emo_text/emo_vector（→情绪）、spk_audio_prompt 零样本克隆；
    infer_v2_5.py 内 sampling_rate=22050。worker 桥协议只透传
    {id,text,voice,out,lang}——克隆经桥真可用（voice=参考音频路径）。
重依赖全部 monkeypatch/临时目录假模型，绝不真加载。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.tts import factory
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.engines import indextts2 as indextts2_mod
from dramaclip.engines.tts.engines.edge import EdgeTtsEngine
from dramaclip.engines.tts.engines.indextts2 import IndexTts2Engine
from dramaclip.engines.tts.engines.kokoro import KokoroEngine


def test_engine_caps_defaults_are_conservative() -> None:
    caps = EngineCaps()
    assert caps.supports_cloning is False
    assert caps.supports_emotion is False
    assert caps.speed_control == "none"
    assert caps.sample_rate == 0


# ---------------------------------------------------------------- edge


def test_edge_caps_reflect_the_cloud_service() -> None:
    caps = EdgeTtsEngine().capabilities()
    assert caps.sample_rate == 24000  # audio-24khz-48kbitrate-mono-mp3
    assert caps.supports_cloning is False
    assert caps.speed_control == "native"  # Communicate(rate=...) 实测存在


def test_edge_availability_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    real = importlib.util.find_spec

    def fake(name: str, *a: object, **k: object) -> object:
        return None if name == "edge_tts" else real(name)  # type: ignore[arg-type]

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    ok, reason = EdgeTtsEngine().is_available()
    assert ok is False
    assert "edge-tts" in reason


def test_edge_availability_probes_the_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dramaclip.engines.tts.engines import edge as edge_mod

    monkeypatch.setattr(edge_mod, "_cloud_reachable", lambda: True)
    ok, reason = EdgeTtsEngine().is_available()
    assert ok is True
    assert "云端可达" in reason

    def boom() -> bool:
        raise OSError("连接超时")

    monkeypatch.setattr(edge_mod, "_cloud_reachable", boom)
    ok, reason = EdgeTtsEngine().is_available()
    assert ok is False
    assert "不可达" in reason and "连接超时" in reason


# ---------------------------------------------------------------- kokoro


def test_kokoro_caps_reflect_model_constants(tmp_path: Path) -> None:
    caps = KokoroEngine(tmp_path).capabilities()
    assert caps.sample_rate == 24000  # kokoro._SAMPLE_RATE
    assert caps.supports_cloning is False
    assert caps.speed_control == "native"  # KPipeline(speed=...) 实测存在


def test_kokoro_availability_reports_missing_model(tmp_path: Path) -> None:
    ok, reason = KokoroEngine(tmp_path / "nowhere").is_available()
    assert ok is False
    assert "缺模型" in reason


def test_kokoro_availability_passes_with_fake_weights(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "kokoro-v1_1-zh.pth").write_bytes(b"\x00")
    ok, reason = KokoroEngine(tmp_path).is_available()
    assert ok is True
    assert reason != ""


# ---------------------------------------------------------------- indextts2


def test_indextts2_caps_declare_cloning(tmp_path: Path) -> None:
    caps = IndexTts2Engine(tmp_path).capabilities()
    assert caps.supports_cloning is True  # 零样本克隆：voice=参考音频路径
    assert caps.sample_rate == 22050  # infer_v2_5.py sampling_rate 实测


def test_indextts2_availability_follows_runtime_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("config.yaml", "gpt.pth", "s2mel.pth"):
        (tmp_path / name).write_bytes(b"\x00")
    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: False)
    ok, reason = IndexTts2Engine(tmp_path).is_available()
    assert ok is False
    assert "隔离" in reason and "venv" in reason

    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: True)
    ok, reason = IndexTts2Engine(tmp_path).is_available()
    assert ok is True


def test_indextts2_availability_reports_missing_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: True)
    ok, reason = IndexTts2Engine(tmp_path / "nothing").is_available()
    assert ok is False
    assert "缺模型" in reason


# ---------------------------------------------------------------- factory


def test_factory_capabilities_reaches_the_real_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.engines.tts.engines import edge as edge_mod

    monkeypatch.setattr(edge_mod, "_cloud_reachable", lambda: True)
    caps = factory.capabilities("edge", tmp_path)
    assert isinstance(caps, EngineCaps)
    assert caps.sample_rate == 24000
    assert caps.available is True


def test_factory_capabilities_catches_probe_explosions(tmp_path: Path) -> None:
    """单引擎探测抛异常不拖垮整体：异常进该条 reason，不向外抛。"""
    caps = factory.capabilities("kokoro", tmp_path)  # 缺模型 → available=False + reason
    assert caps.available is False
    assert caps.reason != ""
    # 未知引擎同样不抛
    unknown = factory.capabilities("vibevoice", tmp_path)
    assert unknown.available is False
    assert "vibevoice" in unknown.reason or "探测失败" in unknown.reason


def test_factory_capabilities_never_touches_supported_set() -> None:
    """registry.engine_ready 的防漂移判据读 factory.supported()：caps 接入不得动它。"""
    assert factory.supported() == frozenset({"edge", "kokoro", "indextts2"})
