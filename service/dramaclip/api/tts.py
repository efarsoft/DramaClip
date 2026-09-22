"""tts 命名空间：试听——配音域的即时反馈，只读语义（不改设置、不下载模型）。

试听的全部价值在于「听到的就是选的那一件」，而三个引擎对不认识的音色一律**静默回退**
（`engines/tts/engines/edge.py:28` 非 zh- 开头改用 DEFAULT_VOICE，`kokoro.py:33` 找不到
voices/<name>.pt 改用 zf_001）。出片路径保留这份宽容是为了兼容升级前的全局 tts.voice 键，
但试听不能跟着宽容：静默换嗓子等于让人拿别人的声音做决定，故这里把回退说破。
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.tts import factory, reference_qc
from dramaclip.engines.tts.base import DEFAULT_VOICE, audio_container, audio_duration_s
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_TTS_PARAM = -32320
_ERR_TTS_SYNTH = -32321

#: 试听短句：一句带停顿、转折和直接引语的台词，标点处理与语气一听便知差别。
PREVIEW_TEXT = "她推开门就愣住了：三年没见的妹妹，张口还是那句「哥，我回来了」。"
#: 上限按「几秒钟的样本」定：本地引擎一句长文可能占着执行池几十秒，那已经是出片不是试听。
MAX_PREVIEW_CHARS = 60
_PREVIEW_DIR = "tts-preview"


def register(router: Router, context: AppContext) -> None:
    router.register("tts.preview", lambda params: preview(context, params))


def preview(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """用指定（缺省取当前生效）引擎+音色合成一句短句，返回本机音频路径。

    失败一律抛 `RpcDomainError` 并带上原因——包括「换个引擎就能出声」的那几种：
    出声的若不是用户选的那件，比不出声更糟。
    """
    engine = str(params.get("engine") or context.settings.get("tts.engine") or "").strip()
    if engine not in factory.supported():
        raise RpcDomainError(
            _ERR_TTS_PARAM,
            f"配音引擎「{engine or '未指定'}」未接入合成工厂，不能试听"
            "（储备资产即便下载也还不能生效）",
        )
    text = str(params.get("text") or PREVIEW_TEXT).strip()
    if text == "":
        raise RpcDomainError(_ERR_TTS_PARAM, "试听文案不能为空")
    if len(text) > MAX_PREVIEW_CHARS:
        raise RpcDomainError(
            _ERR_TTS_PARAM,
            f"试听文案限 {MAX_PREVIEW_CHARS} 字以内（当前 {len(text)} 字）——长文请走出片流程",
        )
    models_dir = context.data_dir / "models"
    voice = _resolve_voice(context, engine, params, models_dir)
    path = _preview_audio(context, engine, voice, text, models_dir)
    duration = audio_duration_s(path)
    if duration <= 0:
        raise RpcDomainError(
            _ERR_TTS_SYNTH, f"试听音频时长无效（{duration:.2f}s）：{path}（换个音色再试）"
        )
    result: dict[str, Any] = {
        "path": str(path),
        "duration_s": round(duration, 3),
        "engine": engine,
        "voice": voice,
        "text": text,
    }
    quality = _reference_quality(engine, voice)
    if quality is not None:
        result["reference_quality"] = quality
    return result


def _reference_quality(engine: str, voice: str) -> dict[str, Any] | None:
    """B6：克隆引擎且 voice 是存在的文件时才附参考音频质检报告。

    附加字段，不阻断不报错：质检是报告不是门禁（poor 也照常合成返回 path，
    用户在试听时看到「这段参考质量差+为什么+怎么补救」，而不是出片后听出来）。
    result 的 schema 无 additionalProperties:false，contract_sync 只钉 required
    集合与方法名单——附加字段属开放集，不动 protocol/*（禁碰）也合法。
    """
    if engine != "indextts2":
        return None  # 固定音色表引擎（edge/kokoro）没有参考音频这一说
    ref = Path(voice)
    if voice == "" or not ref.is_file():
        return None  # 不是文件路径无从质检；合成失败自有报错，这里不替引擎判死
    quality = reference_qc.inspect_reference(ref)
    return {
        "grade": quality.grade,
        "reasons": list(quality.reasons),
        "suggestions": list(quality.suggestions),
    }


def _resolve_voice(
    context: AppContext, engine: str, params: dict[str, Any], models_dir: Path
) -> str:
    """音色取用顺序与出片一致：显式参数 → 该引擎的音色键 → 升级前的全局键。"""
    voice = str(
        params.get("voice")
        or context.settings.get(f"tts.voice.{engine}")
        or context.settings.get("tts.voice")
        or ""
    ).strip()
    _assert_model_present(engine, models_dir)
    _assert_voice_honest(engine, voice, models_dir)
    return voice


def _assert_model_present(engine: str, models_dir: Path) -> None:
    try:
        path = factory.model_dir(models_dir, engine)
    except ValueError:
        return  # model_dir 对云端引擎抛的就是这句：没有本地模型这一说
    if not path.is_dir():
        raise RpcDomainError(
            _ERR_TTS_PARAM,
            f"「{engine}」的模型未下载：{path}（在引擎中心的资产库里下载或手动放置后再试听）",
        )


def _assert_voice_honest(engine: str, voice: str, models_dir: Path) -> None:
    if engine == "edge" and not voice.startswith("zh-"):
        raise RpcDomainError(
            _ERR_TTS_PARAM,
            f"Edge 没有音色「{voice or '未指定'}」——引擎会静默改用 {DEFAULT_VOICE}，"
            "那样听到的不是你要选的那把嗓子",
        )
    if engine == "kokoro":
        pt = factory.model_dir(models_dir, "kokoro") / "voices" / f"{voice}.pt"
        if not pt.is_file():
            raise RpcDomainError(
                _ERR_TTS_PARAM,
                f"Kokoro 没有音色「{voice or '未指定'}」（{pt.name} 不在模型的 voices/ 里）"
                "——引擎会静默改用 zf_001，那已经不是你在挑的音色",
            )


def _preview_audio(
    context: AppContext, engine: str, voice: str, text: str, models_dir: Path
) -> Path:
    """内容寻址：engine/voice/text 全进哈希，同样的三元组不重复合成。"""
    root = context.work_dir / _PREVIEW_DIR
    root.mkdir(parents=True, exist_ok=True)
    key = _content_key(engine, voice, text)
    cached = _find_cached(root, key)
    if cached is not None:
        return cached
    return _synthesize(engine, voice, text, models_dir, root, key)


def _content_key(engine: str, voice: str, text: str) -> str:
    """音色名不进文件名——它是用户可影响的字符串，路径分隔符会借此越出缓存目录。"""
    digest = hashlib.sha1(
        f"{engine}|{voice}|{text}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return f"preview-{engine}-{digest}"


def _find_cached(root: Path, key: str) -> Path | None:
    """扩展名按探到的容器定，所以只能按前缀找；同名多条取字典序首条，保证可复现。"""
    hits = sorted(path for path in root.glob(f"{key}.*") if _has_audio(path))
    return hits[0] if hits else None


def _has_audio(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _synthesize(
    engine: str, voice: str, text: str, models_dir: Path, root: Path, key: str
) -> Path:
    """先写临时名、成功后按真实容器原子搬正：半途失败的残留不能被下次当成缓存播出去。"""
    staging = root / f"{key}.{uuid.uuid4().hex}.mp3"
    try:
        create_tts(engine, models_dir).synthesize(text, voice, staging)
        if not _has_audio(staging):
            raise RuntimeError("引擎返回了空文件（0 字节），没有任何声音可播")
        path = root / f"{key}.{_extension_of(staging)}"
        os.replace(staging, path)
    except Exception as exc:  # noqa: BLE001 - 失败原因必须原样带出，且不换个引擎重试
        raise RpcDomainError(
            _ERR_TTS_SYNTH, f"试听合成失败（引擎={engine}）：{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        staging.unlink(missing_ok=True)
    return path


def _extension_of(path: Path) -> str:
    """格式名要拼进文件名：只留字母数字，探测失败也要有个能用的小写扩展名。"""
    token = audio_container(path).split(",")[0]
    return "".join(char for char in token if char.isalnum()).lower() or "audio"
