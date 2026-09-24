"""能力层自检（规格 §10.3）：文件校验只证明文件在，不证明能推——真跑一段才算数。

ASR 真转写随包样例 ``resources/selftest/sample_zh.wav``（来历见 resources/selftest/README.md）；
TTS 走与 tts.preview 同一条工厂路径真合成一句。结果落盘 ``models/selftest.json``（不落盘则
每次重启都退回「未自检」）：「就绪」= 文件层校验过 + 能力层自检过（§10.1）；
自检失败**不是异常**而是一条诚实结果（ok=False + error 原文）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager.registry import ModelSpec
from dramaclip.infra.paths import resolve_resources_dir

#: 自检短句：够引擎走完「加载→推理→出声」全程，又短到不占用执行池几十秒。
SELFTEST_TEXT = "自检：一二三，今天天气不错，适合测试语音合成。"
_RESULTS_NAME = "selftest.json"


def sample_wav() -> Path:
    """随包 ASR 样例（只读资源，不进 data/）。"""
    return resolve_resources_dir() / "selftest" / "sample_zh.wav"


def run_asr(
    models_dir: Path, spec: ModelSpec, *, device: str = "cpu", compute_type: str = "auto"
) -> dict[str, Any]:
    """ASR 自检：真加载、真转写。调用方保证模型已安装（缺模型是前置错误，不是自检结果）。"""
    sample = sample_wav()
    if not sample.is_file():
        return _fail(f"随包样例音频缺失：{sample}——安装包不完整，请重装")
    started = time.monotonic()
    try:
        # 构建也在自检范围内：「加载成功」本身就是判据的一半（缺 cuDNN、权重损坏
        # 都在构建期炸），不许把加载失败抛成 RPC 内部错误冒充「自检没跑」。
        engine = _build_asr(models_dir, spec, device, compute_type)
        segments = engine.transcribe(sample, "zh")
    except Exception as exc:  # noqa: BLE001 - 自检要的就是真异常原文，不包装不吞
        return _fail(f"加载/推理失败：{type(exc).__name__}: {exc}")
    elapsed = time.monotonic() - started
    text = "".join(segment.text for segment in segments).strip()
    if not text:
        # 随包样例是真人语音（SenseVoice/Whisper 实测都能转出全文）：空结果 = 没跑通。
        # 2026-09-24 实测教训：paraformer 原始输出缺 timestamp 时解析整条丢弃，
        # chars=0 却 ok=true——加载成功 ≠ 出字，假绿比红更坏。
        return _fail(
            "转写结果为空——随包样例是真人语音，空结果说明引擎没真跑通"
            "（常见原因：输出解析丢字，或缺时间戳被整条丢弃）"
        )
    return {
        "ok": True,
        "engine": engine.name,
        "chars": len(text),
        "elapsed_s": round(elapsed, 2),
        "text": text[:60],
    }


def run_tts(models_dir: Path, work_dir: Path, spec: ModelSpec, voice: str) -> dict[str, Any]:
    """TTS 自检：真合成一句短话并验证时长——空文件/0 时长都算不过。"""
    from dramaclip.engines.tts import factory
    from dramaclip.engines.tts.base import audio_duration_s

    try:
        engine_dir = factory.model_dir(models_dir, spec.engine)
    except ValueError:
        engine_dir = None  # 云端引擎（edge）：没有本地模型这一说
    if engine_dir is not None and not engine_dir.is_dir():
        return _fail(f"模型未下载：{engine_dir}——先下载或导入再自检")
    out = work_dir / f"selftest-{spec.engine}.wav"
    started = time.monotonic()
    try:
        factory.create(spec.engine, models_dir).synthesize(SELFTEST_TEXT, voice, out)
    except Exception as exc:  # noqa: BLE001 - 同上：失败原文就是自检结论
        return _fail(f"合成失败：{type(exc).__name__}: {exc}")
    elapsed = time.monotonic() - started
    duration = audio_duration_s(out) if out.is_file() else 0.0
    out.unlink(missing_ok=True)
    if duration <= 0:
        return _fail("合成结果不是有效音频（0 字节或时长无效）")
    return {
        "ok": True,
        "engine": spec.engine,
        "duration_s": round(duration, 2),
        "elapsed_s": round(elapsed, 2),
    }


def _build_asr(models_dir: Path, spec: ModelSpec, device: str, compute_type: str) -> Any:
    from dramaclip.engines.analysis.transcriber import (
        FasterWhisperEngine,
        ParaformerEngine,
        SenseVoiceEngine,
    )

    if spec.engine == "faster_whisper":
        size = spec.model_id.removeprefix("faster-whisper-")
        return FasterWhisperEngine(
            size,
            device=device,
            models_dir=models_dir / "asr" / "faster-whisper",
            compute_type=compute_type,
        )
    if spec.engine == "sensevoice":
        return SenseVoiceEngine(models_dir=models_dir)
    if spec.engine == "paraformer":
        # device/compute_type 是 whisper（ctranslate2）的概念；funasr 栈自己管设备，
        # CPU 就能跑，不硬传免得假装支持没验证过的 GPU 路径。
        return ParaformerEngine(models_dir=models_dir)
    raise ValueError(f"{spec.engine} 没有能力层自检实现（只有 ASR/TTS 有真推理可跑）")


def _fail(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error}


# --------------------------------------------------------------------------- 结果落盘


def load_results(models_dir: Path) -> dict[str, Any]:
    """历史自检结果（key → 结果）。

    文件读坏时返回空表而不是报错：自检结果是可重跑的缓存数据，不是资产——
    丢了就等于「未自检」，这个降级本身是诚实的（UI 会要求重跑，不会发绿灯）。
    """
    path = models_dir / _RESULTS_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_result(models_dir: Path, key: str, result: dict[str, Any]) -> dict[str, Any]:
    """写入一条自检结果（临时名+原子改名：半途崩溃不得留下半截 JSON）。"""
    data = load_results(models_dir)
    stamped = {**result, "at": int(time.time() * 1000)}
    data[key] = stamped
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / _RESULTS_NAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return stamped
