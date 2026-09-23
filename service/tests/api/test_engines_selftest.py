"""engines.selftest：能力层自检（§10.3）——文件在 ≠ 能推，真跑一段才算数。

守卫的口径：
  · 随包样例必须真在包里、真是 16k 单声道 wav（样例丢了自检就是假绿灯）；
  · ASR 自检走真引擎构建路径（本文件打桩引擎，不打桩「是否安装」的前置判据）；
  · 加载/推理失败是**诚实结果**（ok=false + 原文），不是 RPC 异常；
  · 未安装/储备资产是前置错误——没有自检对象，不许假装跑过；
  · 云端域委托 engine_configs.test，不新造第二条连通测试；
  · 每次结果都落账（重启不丢），账本是「就绪=校验+自检」的能力层那一半。
"""

from __future__ import annotations

import sqlite3
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import engines as engines_api
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.infra.model_manager import selftest as selftest_mod
from dramaclip.infra.storage.repos import engine_configs as configs_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError

_TEXT = "欢迎使用短剧切片工具"


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={},
        notifier=Notifier(lambda _m: None),
    )


def _install_whisper_small(tmp_path: Path) -> None:
    """摆出「已安装」的形态：registry.find 命中是自检的前置判据，不打桩。"""
    cache = tmp_path / "models" / "asr/faster-whisper" / "models--Systran--faster-whisper-small"
    snapshot = cache / "snapshots" / ("f" * 40)
    snapshot.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (snapshot / name).write_bytes(b"x" * 16)


class _FakeAsr:
    name = "faster_whisper:small"

    def transcribe(self, wav_path: Path, language: str = "zh", *, hotwords: str = "") -> list:
        assert Path(wav_path).is_file(), "自检必须真把随包样例喂给引擎"
        assert language == "zh"
        return [AsrSegment(start=0.0, end=3.0, text=_TEXT, words=[])]


# ---------------------------------------------------------------- 随包样例


def test_sample_wav_ships_with_the_package() -> None:
    """样例进包是自检成立的前提：格式与时长都量一遍，丢了/坏了这里先红。"""
    sample = selftest_mod.sample_wav()
    assert sample.is_file(), "随包样例缺失：resources/selftest/sample_zh.wav"
    with wave.open(str(sample)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        duration = wav.getnframes() / wav.getframerate()
        assert 5 <= duration <= 30, f"样例时长 {duration:.1f}s 超出 5–30s 约定"


# ---------------------------------------------------------------- ASR


def test_asr_selftest_runs_and_lands_in_the_ledger(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_whisper_small(tmp_path)
    monkeypatch.setattr(selftest_mod, "_build_asr", lambda *_a, **_k: _FakeAsr())
    context = _context(memory_db, tmp_path)

    result = engines_api.run(context, {"model_id": "faster-whisper-small"})

    assert result["ok"] is True
    assert result["chars"] == len(_TEXT)
    assert result["text"] == _TEXT
    assert result["key"] == "faster-whisper-small"
    assert result["elapsed_s"] >= 0
    ledger = engines_api.results(context)
    assert ledger["faster-whisper-small"]["ok"] is True
    assert ledger["faster-whisper-small"]["at"] > 0


def test_asr_selftest_engine_failure_is_an_honest_result(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """加载/推理炸了：ok=false + 异常原文落账——失败本身就是答案，不是 RPC 异常。"""
    _install_whisper_small(tmp_path)

    def boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("cuDNN 找不到")

    monkeypatch.setattr(selftest_mod, "_build_asr", boom)
    context = _context(memory_db, tmp_path)

    result = engines_api.run(context, {"model_id": "faster-whisper-small"})

    assert result["ok"] is False
    assert "cuDNN 找不到" in str(result["error"])
    assert engines_api.results(context)["faster-whisper-small"]["ok"] is False


def test_asr_selftest_forwards_device_and_compute_type_from_settings(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """自检与正式转写必须同一副嗓子：asr.device/asr.compute_type 从设置一路传到构建。

    曾经 _build_asr 只收 device，compute_type 用引擎默认——自检过了不代表正式转写
    用同一档位跑（设置里的 float16 到不了自检，int8 到不了 GPU）。
    """
    _install_whisper_small(tmp_path)
    captured: list[tuple[object, ...]] = []

    def recorder(*args: object) -> _FakeAsr:
        captured.append(args)
        return _FakeAsr()

    monkeypatch.setattr(selftest_mod, "_build_asr", recorder)
    context = _context(memory_db, tmp_path)
    context.settings = {"asr.device": "cuda", "asr.compute_type": "float16"}

    result = engines_api.run(context, {"model_id": "faster-whisper-small"})

    assert result["ok"] is True
    assert len(captured) == 1
    _models_dir, _spec, device, compute_type = captured[0]
    assert device == "cuda"
    assert compute_type == "float16"


def test_asr_selftest_refuses_when_model_missing(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """没装模型就没有自检对象：前置错误说清「先下载或导入」，不许假装跑过。"""
    context = _context(memory_db, tmp_path)
    with pytest.raises(RpcDomainError, match="未安装"):
        engines_api.run(context, {"model_id": "faster-whisper-small"})


def test_reserve_asset_cannot_selftest(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = _context(memory_db, tmp_path)
    with pytest.raises(RpcDomainError, match="尚未接入"):
        engines_api.run(context, {"model_id": "vibevoice-1.5b"})


# ---------------------------------------------------------------- TTS


def test_tts_selftest_synthesizes_and_measures(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.engines.tts import factory

    (tmp_path / "models" / "tts/kokoro/Kokoro-82M-v1.1-zh").mkdir(parents=True)

    class _FakeTts:
        def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
            assert text == selftest_mod.SELFTEST_TEXT
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 16000)  # 1 秒静音
            return out_path

    monkeypatch.setattr(factory, "create", lambda engine, models_dir=None: _FakeTts())
    monkeypatch.setattr(
        "dramaclip.engines.tts.base.audio_duration_s", lambda path: 1.0
    )
    context = _context(memory_db, tmp_path)

    result = engines_api.run(context, {"model_id": "kokoro-82m"})

    assert result["ok"] is True
    assert result["duration_s"] == 1.0
    assert result["key"] == "kokoro-82m"


def test_tts_selftest_reports_missing_weights(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """模型目录不在：不触合成，直接给「先下载或导入」的诚实结论。"""
    result = engines_api.run(_context(memory_db, tmp_path), {"model_id": "kokoro-82m"})
    assert result["ok"] is False
    assert "未下载" in str(result["error"])


# ---------------------------------------------------------------- 云端域


def test_cloud_selftest_delegates_to_engine_configs(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configs_repo.create(
        memory_db, "llm", "测试配置", "https://api.example.com", "key-1", "model-x"
    )
    configs_repo.set_enabled(memory_db, "llm", str(config["id"]))
    seen: dict[str, str] = {}

    def fake_test(_context: object, params: dict[str, str]) -> dict[str, object]:
        seen.update(params)
        return {"ok": True, "latency_s": 0.5, "error": None}

    monkeypatch.setattr(engines_api.engine_configs, "test", fake_test)

    result = engines_api.run(_context(memory_db, tmp_path), {"domain": "llm"})

    assert result["ok"] is True
    assert result["key"] == "cloud:llm"
    assert seen["base_url"] == "https://api.example.com"
    assert seen["model"] == "model-x"


def test_cloud_selftest_without_enabled_config_says_so(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(RpcDomainError, match="没有启用中的配置"):
        engines_api.run(_context(memory_db, tmp_path), {"domain": "llm"})


def test_selftest_needs_a_target(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(RpcDomainError) as exc:
        engines_api.run(_context(memory_db, tmp_path), {})
    assert exc.value.code == -32020


def test_ledger_survives_reload_and_ignores_corruption(tmp_path: Path) -> None:
    models = tmp_path / "models"
    selftest_mod.save_result(models, "faster-whisper-small", {"ok": True, "chars": 56})
    assert selftest_mod.load_results(models)["faster-whisper-small"]["chars"] == 56
    # 账本读坏 = 空表（未自检），不是异常：UI 会要求重跑，不会发绿灯
    (models / "selftest.json").write_text("{broken", encoding="utf-8")
    assert selftest_mod.load_results(models) == {}
