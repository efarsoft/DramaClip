"""engines 命名空间：能力层自检（规格 §10.3）。

校验 = 文件层（models.verify），自检 = 能力层（本文件），两者都过才叫 ready。
云端域（llm 等）不新造第二条连通测试——委托既有 engine_configs.test()，
这里只负责「找到启用中的那份配置」并把结果并入同一张自检账本。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.api import engine_configs
from dramaclip.api.context import AppContext
from dramaclip.infra.model_manager import downloader, registry
from dramaclip.infra.model_manager import selftest as selftest_mod
from dramaclip.infra.storage.repos import engine_configs as configs_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_SELFTEST_PARAM = -32020
_ERR_SELFTEST_STATE = -32021


def register(router: Router, context: AppContext) -> None:
    router.register("engines.selftest", lambda params: run(context, params))
    router.register("engines.selftest_results", lambda params: results(context))


def run(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """跑一次能力层自检并落账：{model_id}（本地 ASR/TTS）或 {domain}（云端连通）。

    同步 RPC：ASR 自检在 CPU 上可能十几秒（§10.6），期间资产行由前端置进行中态。
    """
    models_dir = context.data_dir / "models"
    domain = str(params.get("domain") or "").strip()
    model_id = str(params.get("model_id") or "").strip()
    if domain:
        key, result = f"cloud:{domain}", _cloud(context, domain)
    elif model_id:
        key = model_id
        result = _local(context, models_dir, model_id)
    else:
        raise RpcDomainError(_ERR_SELFTEST_PARAM, "model_id 与 domain 至少要给一个")
    return {**selftest_mod.save_result(models_dir, key, result), "key": key}


def results(context: AppContext) -> dict[str, Any]:
    """历史自检账本（key → 结果，含 at 时间戳）：就绪口径的能力层那一半。"""
    return selftest_mod.load_results(context.data_dir / "models")


def _local(context: AppContext, models_dir: Path, model_id: str) -> dict[str, Any]:
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_SELFTEST_PARAM, f"未知模型: {model_id}")
    if not registry.engine_ready(spec):
        # 工厂都构建不出来的引擎，自检没有对象——这不是失败，是「还轮不到」。
        raise RpcDomainError(
            _ERR_SELFTEST_STATE, f"{spec.name} 的引擎尚未接入工厂，储备资产暂不能自检"
        )
    if spec.kind == "asr":
        return _asr(context, models_dir, spec)
    if spec.kind == "tts":
        return _tts(context, models_dir, spec)
    raise RpcDomainError(
        _ERR_SELFTEST_PARAM, f"{spec.name} 没有能力层自检（只有 ASR/TTS 有真推理可跑）"
    )


def _asr(context: AppContext, models_dir: Path, spec: registry.ModelSpec) -> dict[str, Any]:
    if registry.find(spec, models_dir) is None:
        raise RpcDomainError(
            _ERR_SELFTEST_STATE, f"{spec.name} 未安装——自检需要真实权重，请先下载或导入"
        )
    device = str(context.settings.get("asr.device") or "cpu")
    return selftest_mod.run_asr(models_dir, spec, device=device)


def _tts(context: AppContext, models_dir: Path, spec: registry.ModelSpec) -> dict[str, Any]:
    voice = str(
        context.settings.get(f"tts.voice.{spec.engine}") or context.settings.get("tts.voice") or ""
    )
    return selftest_mod.run_tts(models_dir, context.work_dir, spec, voice)


def _cloud(context: AppContext, domain: str) -> dict[str, Any]:
    configs = configs_repo.list_by_domain(context.conn, domain)
    enabled = next((config for config in configs if config.get("enabled")), None)
    if enabled is None:
        raise RpcDomainError(
            _ERR_SELFTEST_STATE,
            f"能力域 {domain} 没有启用中的配置——先在「云端配置」里配好并启用再自检",
        )
    # 委托既有连通测试（§10.6：只调用，不改 engine_configs 的实现）
    return engine_configs.test(
        context,
        {
            "base_url": str(enabled.get("base_url") or ""),
            "api_key": str(enabled.get("api_key") or ""),
            "model": str(enabled.get("model") or ""),
        },
    )
