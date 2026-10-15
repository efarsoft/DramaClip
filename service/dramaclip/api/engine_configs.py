"""engine_configs 命名空间：云端/服务端点配置的多实例管理（单启用）。

启用即镜像：配置生效时把连接要素写进对应域的既有设置键（llm.* / asr.* / tts.* /
vision.cloud*），运行时消费方零改动——引擎选择仍是设置键语义，配置表只是另一只手。
"""

from __future__ import annotations

import json
import tempfile
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable
from dramaclip.infra.storage.repos import engine_configs as configs_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_BAD = -32310
_ERR_NOT_FOUND = -32311

_DOMAINS = ("llm", "tts_cloud", "asr_cloud", "image", "video")

# 启用即镜像：域 → 设置键写法（消费方读的还是原设置键，零改动）。
_MIRROR: dict[str, Callable[[dict[str, Any]], dict[str, str]]] = {
    "asr_cloud": lambda cfg: {
        "asr.engine": "dashscope_paraformer",
        "asr.api_key": str(cfg["api_key"]),
        "asr.model": str(cfg["model"]),
    },
    "tts_cloud": lambda cfg: {
        "tts.engine": "cosyvoice_cloud",
        "tts.api_key": str(cfg["api_key"]),
        "tts.model": str(cfg["model"]),
    },
    # 视觉云端：OpenAI 兼容端点（qwen-vl 等）；vision.cloud=1 时 runtime 走云端会话
    "image": lambda cfg: {
        "vision.cloud": "1",
        "vision.cloud_base_url": str(cfg["base_url"]),
        "vision.cloud_api_key": str(cfg["api_key"]),
        "vision.cloud_model": str(cfg["model"]),
    },
}


def register(router: Router, context: AppContext) -> None:
    router.register("engine_configs.list", lambda params: _list(context, params))
    router.register("engine_configs.create", lambda params: create(context, params))
    router.register("engine_configs.update", lambda params: update(context, params))
    router.register("engine_configs.delete", lambda params: delete(context, params))
    router.register("engine_configs.enable", lambda params: enable(context, params))
    router.register("engine_configs.test", lambda params: test(context, params))


def _list(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    domain = str(params.get("domain", ""))
    _assert_domain(domain)
    return {"configs": configs_repo.list_by_domain(context.conn, domain)}


def create(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    domain, name, base_url, model = _fields(params)
    api_key = str(params.get("api_key", ""))
    config = configs_repo.create(context.conn, domain, name, base_url, api_key, model)
    if params.get("enable"):
        _enable(context, domain, str(config["id"]))
        refreshed = configs_repo.get(context.conn, str(config["id"]))
        if refreshed is not None:
            config = refreshed
    return config


def update(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    config_id = str(params.get("id", ""))
    name = str(params.get("name", "")).strip()
    if name == "":
        raise RpcDomainError(_ERR_BAD, "名称不能为空")
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    configs_repo.update(
        context.conn,
        config_id,
        name=name,
        base_url=str(params.get("base_url", "")),
        api_key=str(params.get("api_key", "")),
        model=str(params.get("model", "")),
    )
    updated = configs_repo.get(context.conn, config_id)
    assert updated is not None, "更新后配置丢失"
    # 启用中的配置被编辑：镜像同步到 settings，保证即时生效
    if updated["enabled"]:
        _mirror(context, str(updated["domain"]), updated)
    return updated


def delete(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    config_id = str(params.get("id", ""))
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    if existing["enabled"]:
        raise RpcDomainError(_ERR_BAD, "启用中的配置不能删除，请先启用其他配置")
    configs_repo.delete(context.conn, config_id)
    return {"ok": True}


def enable(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """启用一条配置；带 local=true 时清空该域全部启用（切回本地引擎，选本地模型用）。"""
    if params.get("local"):
        domain = str(params.get("domain", "")).strip()
        _assert_domain(domain)
        configs_repo.clear_enabled(context.conn, domain)
        return {"ok": True}
    config_id = str(params.get("id", ""))
    existing = configs_repo.get(context.conn, config_id)
    if existing is None:
        raise RpcDomainError(_ERR_NOT_FOUND, f"配置不存在: {config_id}")
    configs_repo.set_enabled(context.conn, str(existing["domain"]), config_id)
    _mirror(context, str(existing["domain"]), existing)
    enabled = configs_repo.get(context.conn, config_id)
    assert enabled is not None
    return enabled


def test(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """连通性测试：按域发一次真实最小请求（LLM ping / ASR 短音频转写 / TTS 单字合成 / VL 单图）。"""
    domain = str(params.get("domain") or "").strip()
    base_url = str(params.get("base_url", ""))
    api_key = str(params.get("api_key", ""))
    model = str(params.get("model", ""))
    if domain in ("", "llm"):
        return _test_llm(base_url, api_key, model)
    if domain == "asr_cloud":
        return _test_asr(api_key, model)
    if domain == "tts_cloud":
        return _test_tts(api_key, model)
    if domain in ("image", "video"):
        return _test_vision(base_url, api_key, model)
    raise RpcDomainError(_ERR_BAD, f"不支持的能力域: {domain}")


def _test_llm(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    if base_url == "" or model == "":
        raise RpcDomainError(_ERR_BAD, "base_url 与 model 不能为空")
    try:
        client = LlmClient(
            LlmConfig(base_url=base_url, api_key=api_key, model=model),
            timeout_s=30.0,
        )
        latency = client.ping()
    except LlmUnavailable as exc:
        return {"ok": False, "latency_s": None, "error": str(exc)}
    return {"ok": True, "latency_s": round(latency, 2), "error": None}


def _test_asr(api_key: str, model: str) -> dict[str, Any]:
    """ASR 连通：0.5s 静音 wav 走一次真实文件转写（异步任务提交→轮询，端到端可信）。"""
    import time

    from dramaclip.engines.analysis.transcriber import DashscopeParaformerEngine

    if api_key.strip() == "" or model.strip() == "":
        return {"ok": False, "latency_s": None, "error": "API Key 与模型不能为空"}
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "ping.wav"
        _write_silent_wav(wav, seconds=0.5)
        try:
            DashscopeParaformerEngine(api_key=api_key, model=model).transcribe(wav)
        except Exception as exc:  # noqa: BLE001 - 连通失败是一条诚实结果
            return {"ok": False, "latency_s": None, "error": str(exc)[:300]}
    return {"ok": True, "latency_s": round(time.monotonic() - started, 2), "error": None}


def _test_tts(api_key: str, model: str) -> dict[str, Any]:
    """TTS 连通：合成单字「好」落临时文件。"""
    import time

    from dramaclip.engines.tts.engines.dashscope import DashscopeCosyVoiceEngine

    if api_key.strip() == "" or model.strip() == "":
        return {"ok": False, "latency_s": None, "error": "API Key 与模型不能为空"}
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            DashscopeCosyVoiceEngine(api_key=api_key, model=model).synthesize(
                "好", "", Path(tmp) / "ping.wav"
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "latency_s": None, "error": str(exc)[:300]}
    return {"ok": True, "latency_s": round(time.monotonic() - started, 2), "error": None}


def _test_vision(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """视觉连通：1x1 图走一次多模态 chat（OpenAI 兼容端点）。"""
    import time

    if base_url.strip() == "" or api_key.strip() == "" or model.strip() == "":
        return {"ok": False, "latency_s": None, "error": "接口地址、API Key 与模型不能为空"}
    # 1x1 白色 PNG（43 字节），只为验证鉴权与多模态通路
    pixel = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    payload = json.dumps({
        "model": model,
        "max_tokens": 16,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{pixel}"}},
                {"type": "text", "text": "用两个字回答这张图的颜色"},
            ],
        }],
    }).encode()
    started = time.monotonic()
    request = urllib.request.Request(
        f"{base_url.strip().rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key.strip()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "latency_s": None, "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "latency_s": None, "error": str(exc)[:300]}
    return {"ok": True, "latency_s": round(time.monotonic() - started, 2), "error": None}


def _write_silent_wav(path: Path, *, seconds: float = 0.5) -> None:
    """0.5s 8kHz 单声道静音 wav（转写结果为空段，但任务链路完整走通）。"""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * seconds))


def _fields(params: dict[str, Any]) -> tuple[str, str, str, str]:
    domain = str(params.get("domain", "")).strip()
    name = str(params.get("name", "")).strip()
    base_url = str(params.get("base_url", "")).strip().rstrip("/")
    model = str(params.get("model", "")).strip()
    if domain not in _DOMAINS:
        raise RpcDomainError(_ERR_BAD, f"不支持的能力域: {domain}")
    if name == "":
        raise RpcDomainError(_ERR_BAD, "名称不能为空")
    return domain, name, base_url, model


def _assert_domain(domain: str) -> None:
    if domain not in _DOMAINS:
        raise RpcDomainError(_ERR_BAD, f"不支持的能力域: {domain}")


def _enable(context: AppContext, domain: str, config_id: str) -> None:
    configs_repo.set_enabled(context.conn, domain, config_id)
    updated = configs_repo.get(context.conn, config_id)
    if updated is not None:
        _mirror(context, domain, updated)


def _mirror(context: AppContext, domain: str, config: dict[str, Any]) -> None:
    """启用配置镜像到既有设置键：llm 三键（历史路径）或各云端域的映射表。"""
    from dramaclip.infra.storage.repos import settings as settings_repo

    if domain == "llm":
        _mirror_llm_settings(context, config)
        return
    builder = _MIRROR.get(domain)
    if builder is None:
        return
    for key, value in builder(config).items():
        settings_repo.set_value(context.conn, key, value)
        context.settings[key] = value


def _mirror_llm_settings(context: AppContext, config: dict[str, Any]) -> None:
    """启用中的 LLM 配置镜像到 llm.* 三键——既有消费方零改动。"""
    from dramaclip.infra.storage.repos import settings as settings_repo

    mirror = {
        "llm.base_url": str(config["base_url"]),
        "llm.api_key": str(config["api_key"]),
        "llm.model": str(config["model"]),
    }
    for key, value in mirror.items():
        settings_repo.set_value(context.conn, key, value)
        context.settings[key] = value
