"""TTS 引擎工厂（按 settings tts.engine 实例化）。

``supported()`` 与 ``create()`` 共用 ``_MODEL_DIRS`` 这一张表：模型清单里的
「引擎已接入」判据（``registry.engine_ready``）读的就是这里。任何一处再单独维护一份
名单，「就绪」就会退回成猜的——旧版引擎卡把某个引擎写死成 ``ok: true`` 正是这么来的。
"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.tts.base import TtsEngine

# 引擎 → 模型子目录（相对 models_dir）；None = 云端引擎，不需要本地模型。
_MODEL_DIRS: dict[str, Path | None] = {
    "edge": None,
    "kokoro": Path("tts") / "kokoro" / "Kokoro-82M-v1.1-zh",
}


def supported() -> frozenset[str]:
    """本工厂真能实例化出来的引擎名。"""
    return frozenset(_MODEL_DIRS)


def model_dir(models_dir: Path, engine: str) -> Path:
    """引擎实际加载模型的目录——与 registry 里该引擎登记项的 placement 必须是同一个地方。

    没有默认引擎：默认值等于替调用方回答「用哪个引擎」，漏传参数会安静地读错目录。
    """
    relative = _MODEL_DIRS[engine]
    if relative is None:
        raise ValueError(f"{engine} 是云端引擎，没有本地模型目录")
    return models_dir / relative


def create(engine: str, models_dir: Path | None = None) -> TtsEngine:
    if engine == "edge":
        from dramaclip.engines.tts.engines.edge import EdgeTtsEngine

        return EdgeTtsEngine()
    if engine == "kokoro":
        from dramaclip.engines.tts.engines.kokoro import KokoroEngine

        return KokoroEngine(_local_dir(engine, models_dir))
    available = " / ".join(sorted(supported()))
    raise ValueError(f"未知 TTS 引擎: {engine}（可用: {available}）")


def _local_dir(engine: str, models_dir: Path | None) -> Path:
    if models_dir is None:
        raise ValueError(f"{engine} 引擎需要 models_dir")
    return model_dir(models_dir, engine)
