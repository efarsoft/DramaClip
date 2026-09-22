"""models 命名空间：list / download / verify（资产体检）/ import（导入向导）/ delete。"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.jobs import STATUS_RUNNING
from dramaclip.infra.model_manager import downloader, importer, registry
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_MODEL_NOT_FOUND = -32010
_ERR_MODEL_STATE = -32011
_ERR_IMPORT_PARAM = -32012

_ENDPOINT_DEFAULTS: dict[str, str] = {
    "hf_mirror": "https://hf-mirror.com",
    "modelscope": "https://modelscope.cn",
    "huggingface": "https://huggingface.co",
}


def endpoints(context: AppContext) -> dict[str, str]:
    """下载端点：settings 可覆盖镜像站（键 download.hf_mirror / download.ms_base）。"""
    out = dict(_ENDPOINT_DEFAULTS)
    for key, setting in (("hf_mirror", "download.hf_mirror"), ("modelscope", "download.ms_base")):
        value = (context.settings.get(setting) or "").strip()
        if value:
            out[key] = value
    return out


def register(router: Router, context: AppContext) -> None:
    router.register("models.list", lambda _params: list_models(context))
    router.register("models.download", lambda params: download(context, params))
    router.register("models.scan_local", lambda params: scan_local(context))
    router.register("models.verify", lambda params: verify(context, params))
    router.register("models.relayout", lambda params: relayout(context, params))
    router.register("models.import_inspect", lambda params: import_inspect(context, params))
    router.register("models.import_commit", lambda params: import_commit(context, params))
    router.register("models.import_records", lambda params: import_records(context))
    router.register("models.import_forget", lambda params: import_forget(context, params))
    router.register("models.runtime_status", lambda params: runtime_status(context, params))
    router.register("models.install_runtime", lambda params: install_runtime(context, params))
    router.register("models.indextts_status", lambda params: indextts_status(context, params))
    router.register("models.install_indextts", lambda params: install_indextts(context, params))
    router.register("models.delete", lambda params: delete(context, params))


def list_models(context: AppContext) -> list[dict[str, Any]]:
    """内置清单的状态，加上「本地导入」的登记项，附各源仓库主页。

    这里只有内置清单的行：每一行都必须有 ``model_id``，因为「选为生效」按它落配置。
    清单外的目录（业主给的、认不出身份的）在 ``models.import_records`` 里——把它伪装成
    一行模型就等于给它一个身份，也就给了它一个「选为生效」。
    """
    models_dir = context.data_dir / "models"
    eps = endpoints(context)
    items = registry.list_models(models_dir)
    for item in items:
        item["sources"] = [
            {**source, "web_url": downloader.web_url(str(source["kind"]), str(source["repo"]), eps)}
            for source in item["sources"]
        ]
    return _attach_imports(items, importer.records(models_dir))


def verify(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """资产体检报告：给 model_id 报那一项，不给则报所有已落盘的。

    为什么批量只覆盖已安装：总览页一次拉全，把 11 个未安装项逐条报「目录不存在」是噪声
    ——它们的状态在 models.list 里已经有了。指定 model_id 时未安装照样回完整报告，
    体检弹窗要能告诉业主「缺哪一项」而不是弹个异常。
    """
    models_dir = context.data_dir / "models"
    model_id = str(params.get("model_id") or "")
    if model_id:
        spec = downloader.spec_by_id(model_id)
        if spec is None:
            raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
        specs: list[registry.ModelSpec] = [spec]
    else:
        specs = [
            spec
            for spec in registry.builtin_specs()
            if registry.detect_status(models_dir, spec)["status"] == "installed"
        ]
    return [registry.verify(models_dir, spec) for spec in specs]


def relayout(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """whisper 存量 ``snapshots/main`` 就地迁移成提交号布局：改名 + 补 refs/trees，零重新下载。

    同步短活（一次在线解析提交号 + 目录改名 + 逐文件哈希，秒级），不建作业；
    解析不到提交号/目标修订已并存时把 ValueError 原文转域错误——那都是要业主
    看见的诚实结论，不是可以吞掉的内部状态。
    """
    model_id = str(params.get("model_id") or "")
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    try:
        result = downloader.relayout_whisper_cache(
            spec, context.data_dir / "models", endpoints(context)
        )
    except ValueError as exc:
        raise RpcDomainError(_ERR_MODEL_STATE, str(exc)) from exc
    if result["migrated"]:
        context.notifier.log("info", f"{spec.name}：缓存布局已就地迁移到 {result['path']}")
    return result


def download(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    model_id = str(params.get("model_id", ""))
    source = str(params.get("source") or "auto")
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    if not spec.sources():
        # 无源不等于可下载：拼出空 repo 的 URL 只会以一堆重试收场，指回导入这条路。
        raise RpcDomainError(
            _ERR_MODEL_STATE, f"{spec.name} 无自动下载源，请用「导入模型」放入 {spec.placement}"
        )
    if source != "auto" and source not in dict(spec.sources()):
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 不支持来源 {source}")
    models_dir = context.data_dir / "models"
    if registry.find(spec, models_dir) is not None:
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 已安装")
    job_id = context.job_store.create("model_download", ref_id=model_id)
    # 必须置 running：看门狗的回写条件是 status=="running"，而启动清扫只扫 running——
    # 不置位则下载成功后记录永远停在 pending，且重启也清不掉（队列页永久假"下载中"）。
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == STATUS_RUNNING:
            context.job_store.mark_completed(job_id)
        context.cancel_events.pop(job_id, None)

    downloader.download_in_background(
        spec,
        models_dir,
        context.notifier,
        cancel_event,
        done_event,
        endpoints=endpoints(context),
        source=source,
    )
    threading.Thread(target=_watch, daemon=True, name=f"dl-watch-{model_id}").start()
    return {"job_id": job_id}


def runtime_status(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """CUDA 运行库安装态（GpuCard 状态机第四档的判据）。"""
    from dramaclip.infra.model_manager import cuda_runtime

    return cuda_runtime.status(context.data_dir)


def install_runtime(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """下载并启用 CUDA 运行库（作业模式：进度走 set_progress，可取消）。"""
    from dramaclip.infra.model_manager import cuda_runtime

    if cuda_runtime.status(context.data_dir)["installed"]:
        raise RpcDomainError(_ERR_MODEL_STATE, "CUDA 运行库已安装")
    _active = [
        j for j in context.job_store.list_recent(limit=50, active_only=True)
        if j["type"] == "cuda_runtime"
    ]
    if _active:
        raise RpcDomainError(_ERR_MODEL_STATE, "已有安装任务进行中，请等待完成或取消")
    job_id = context.job_store.create("cuda_runtime", ref_id="cuda-runtime")
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _run() -> None:
        try:
            cuda_runtime.install(
                context.data_dir,
                cancel=cancel_event,
                on_progress=lambda percent: context.job_store.set_progress(
                    job_id, float(percent), "下载 CUDA 运行库"
                ),
            )
            context.notifier.log("info", "CUDA 运行库安装完成，重启服务后对已运行进程生效")
        except Exception as exc:  # noqa: BLE001 - 作业失败原样落 error
            context.job_store.mark_failed(job_id, str(exc))
        finally:
            done_event.set()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == "running":
            context.job_store.mark_completed(job_id)
        context.cancel_events.pop(job_id, None)

    threading.Thread(target=_run, daemon=True, name="cuda-runtime-install").start()
    threading.Thread(target=_watch, daemon=True, name="cuda-runtime-watch").start()
    return {"job_id": job_id}



def scan_local(context: AppContext) -> dict[str, Any]:
    """重新探测 models/：手动放进目录的模型即刻被认出来。

    这里不叫「导入」：真正的导入是 ``models.import_commit``（识别 + 体检 + 落位 + 登记）。
    本方法只是让引擎中心刷新一次磁盘状态，登记本坏了也在这里说一声。
    """
    models_dir = context.data_dir / "models"
    found = [
        item
        for item in registry.list_models(models_dir)
        if item["status"] == "installed"
    ]
    context.notifier.log("info", f"模型目录重新探测完成：{len(found)} 个模型可用")
    return {
        "installed": found,
        "total": len(found),
        "import_error": importer.records_error(models_dir),
    }


def delete(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    model_id = str(params.get("model_id", ""))
    spec = downloader.spec_by_id(model_id)
    if spec is None:
        raise RpcDomainError(_ERR_MODEL_NOT_FOUND, f"未知模型: {model_id}")
    models_dir = context.data_dir / "models"
    records = [r for r in importer.records(models_dir) if r.get("model_id") == model_id]
    resolved = registry.find(spec, models_dir)
    if resolved is None and not records:
        raise RpcDomainError(_ERR_MODEL_STATE, f"{spec.name} 未安装")
    # 只允许删除 models/ 目录内的内容（防误删仓库文件）
    root = models_dir.resolve()
    removed: list[str] = []
    for record in records:
        path = Path(str(record["path"]))
        importer.forget(models_dir, path)
        if _inside(models_dir, str(record["path"])):
            # 导入落在库内的副本：连整个资产目录一起清掉，只删快照会留下引用壳目录
            shutil.rmtree(path.resolve(), ignore_errors=True)
        # 库外的登记项（仅登记 / 并存）：只撤登记，业主自己的目录由他自己处置
        removed.append(str(path))
    if resolved is not None:
        target = resolved.resolve()
        if root not in target.parents:
            raise RpcDomainError(_ERR_MODEL_STATE, "目标不在模型目录内，拒绝删除")
        shutil.rmtree(target, ignore_errors=True)
        removed.append(str(target))
        importer.forget(models_dir, resolved)
    return {"ok": True, "removed": removed}


def _inside(models_dir: Path, path: str) -> bool:
    """登记路径是否真在库里：库外的只有「撤销登记」这一种处置。"""
    if not path:
        return False
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    return models_dir.resolve() in target.parents


# --------------------------------------------------------------------------- 导入向导（D4）


def import_inspect(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """向导第 ② 步：认一认业主挑的目录，只读不落盘。

    importer 的 ValueError 一律翻成领域错误码——向导要显示「缺哪几项」这种人话，
    不是一个 JSON-RPC 内部异常。
    """
    source = _source_param(params)
    try:
        return importer.inspect(context.data_dir / "models", source)
    except ValueError as exc:
        raise RpcDomainError(_ERR_MODEL_STATE, str(exc)) from exc


def import_commit(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """向导第 ③ 步：把目录落进资产库（GB 级复制，所以是作业）。

    判据不在这里重写：能不能落位、冲突怎么裁决，全部由 ``importer.commit`` 说了算，
    它拒绝时抛的 ValueError 原样进作业的 ``error``——UI 上看到的话术与引擎侧同源。
    作业故意不挂 ``cancel_events``：复制半途没有「撤销」可言，能停下一半只会留下一份
    比原状更糟的资产，所以宁可让业主等，也不给一个骗人的取消按钮。
    """
    source = _source_param(params)
    models_dir = context.data_dir / "models"
    job_id = context.job_store.create("model_import", ref_id=source.name)
    # 必须置 running：看门狗只给 running 收尾，漏了这一句作业会永远停在 pending（同 download）
    context.job_store.mark_running(job_id)
    done_event = threading.Event()

    def _progress(done: int, total: int) -> None:
        percent = 100.0 if total <= 0 else round(done * 100.0 / total, 1)
        message = f"落位 {importer.human_bytes(done)} / {importer.human_bytes(total)}"
        context.job_store.set_progress(job_id, percent, message)
        context.notifier.progress(job_id, percent, message)

    def _run() -> None:
        try:
            result = importer.commit(
                models_dir,
                source,
                mode=str(params.get("mode") or ""),
                on_conflict=str(params.get("on_conflict") or ""),
                allow_incomplete=bool(params.get("allow_incomplete") or False),
                external_kind=str(params.get("external_kind") or ""),
                label=str(params.get("label") or ""),
                on_progress=_progress,
            )
            context.notifier.log(
                "info",
                f"{result['mode']} 落位完成：{result['path']}"
                + ("（体检不通过，已按不完整导入登记）" if result["incomplete"] else ""),
            )
        except Exception as exc:  # noqa: BLE001 - 拒绝话术要原样回给向导
            context.job_store.mark_failed(job_id, str(exc))
        finally:
            done_event.set()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == STATUS_RUNNING:
            context.job_store.mark_completed(job_id)

    threading.Thread(target=_run, daemon=True, name=f"import-{source.name}").start()
    threading.Thread(target=_watch, daemon=True, name=f"import-watch-{job_id[:8]}").start()
    return {"job_id": job_id}


def import_records(context: AppContext) -> dict[str, Any]:
    """登记本全文：来源标记与「外部资产」都在这一个形状里。

    内置清单外的目录不进 ``models.list``——那一列每行都要有身份才能「选为生效」；这里给的是
    登记项本身，认不出身份的 ``model_id`` 为 null，UI 据此只能提供「撤销登记」。
    """
    models_dir = context.data_dir / "models"
    return {"records": importer.records(models_dir), "error": importer.records_error(models_dir)}


def import_forget(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """撤销一条登记：业主放在自己盘上的字节，只能由他自己处置。

    库内的路径一律拒绝——那份是真资产，只撤登记就等于把它变成「躺在库里但没人知道」；
    那种情况该走的是 models.delete（连文件一起清）。
    """
    models_dir = context.data_dir / "models"
    stored = str(_source_param(params, "请指明要撤销哪一条登记"))
    record = next(
        (item for item in importer.records(models_dir) if str(item.get("path") or "") == stored),
        None,
    )
    if record is None:
        raise RpcDomainError(_ERR_MODEL_STATE, f"登记本里没有这条路径: {stored}")
    if _inside(models_dir, stored):
        raise RpcDomainError(
            _ERR_MODEL_STATE, f"{stored} 在模型库内，是已落位的资产；请用「移除」处置而不是撤销登记"
        )
    importer.forget(models_dir, Path(stored))
    return {"ok": True, "path": stored}


def _source_param(params: dict[str, Any], hint: str = "请先选择要导入的模型目录") -> Path:
    raw = str(params.get("path") or "").strip()
    if not raw:
        raise RpcDomainError(_ERR_IMPORT_PARAM, f"缺少 path：{hint}")
    return Path(raw)


def _attach_imports(
    items: list[dict[str, Any]], records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """把「本地导入」挂到清单行上：移除时才分得清该删库内副本还是只撤登记。

    一个模型可能有多条登记（先仅登记、后来又复制进库）：优先挂路径与已安装位置一致的那条，
    它才是引擎此刻真正读到的那份。清单外的登记项不属于任何行，留在登记本里由
    ``models.import_records`` 交出。
    """
    for item in items:
        item["imported"] = None
    claimed: set[int] = set()
    for item in items:
        index = _pick_record(records, claimed, str(item["model_id"]), item.get("path"))
        if index is not None:
            claimed.add(index)
            item["imported"] = records[index]
    return items


def _pick_record(
    records: list[dict[str, Any]], claimed: set[int], model_id: str, installed: Any
) -> int | None:
    """挑一条属于这个模型的登记：装到位的那条优先，其次按登记顺序。"""
    candidates = [
        index
        for index, record in enumerate(records)
        if index not in claimed and record.get("model_id") == model_id
    ]
    for index in candidates:
        if _matches_installed(str(records[index].get("path") or ""), installed):
            return index
    return candidates[0] if candidates else None


def _matches_installed(recorded: str, installed: Any) -> bool:
    """登记路径是不是引擎此刻读到的那一份：同一目录，或它是包住快照的缓存根。

    不能直接比字符串——whisper 的登记落在缓存根（``models--…``），清单里的 ``path`` 却是
    ``snapshots/<hash>``，一比就永远不相等，行上会挂回那条躺在库外的旧登记。
    """
    if not recorded or not installed:
        return False
    stored, landed = Path(recorded), Path(str(installed))
    return stored == landed or stored in landed.parents


def indextts_status(context: AppContext, _params: dict[str, Any]) -> dict[str, Any]:
    """IndexTTS 运行环境安装态（引擎卡内联安装槽的判据）。"""
    from dramaclip.infra.model_manager import indextts_runtime

    return indextts_runtime.status(context.data_dir)


def install_indextts(context: AppContext, _params: dict[str, Any]) -> dict[str, Any]:
    """引导 IndexTTS 运行环境（作业模式：uv → venv → torch → 依赖 → 源码 → 自检）。"""
    from dramaclip.infra.model_manager import indextts_runtime

    if indextts_runtime.status(context.data_dir)["installed"]:
        raise RpcDomainError(_ERR_MODEL_STATE, "IndexTTS 运行环境已就绪")
    _active = [
        j for j in context.job_store.list_recent(limit=50, active_only=True)
        if j["type"] == "indextts_runtime"
    ]
    if _active:
        raise RpcDomainError(_ERR_MODEL_STATE, "已有安装任务进行中，请等待完成或取消")
    job_id = context.job_store.create("indextts_runtime", ref_id="indextts-runtime")
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _run() -> None:
        try:
            indextts_runtime.install(
                context.data_dir,
                cancel=cancel_event,
                on_progress=lambda percent, stage: context.job_store.set_progress(
                    job_id, float(percent), stage
                ),
            )
            context.notifier.log("info", "IndexTTS 运行环境安装完成")
        except Exception as exc:  # noqa: BLE001 - 作业失败原样落 error
            context.job_store.mark_failed(job_id, str(exc))
        finally:
            done_event.set()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == "running":
            context.job_store.mark_completed(job_id)
        context.cancel_events.pop(job_id, None)

    threading.Thread(target=_run, daemon=True, name="indextts-runtime-install").start()
    threading.Thread(target=_watch, daemon=True, name="indextts-runtime-watch").start()
    return {"job_id": job_id}
