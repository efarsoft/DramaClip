"""服务装配：存储初始化、路由、执行池与连接生命周期（docs/service/00 启动时序）。"""

from __future__ import annotations

import signal
import sqlite3
import threading
import faulthandler
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from dramaclip import PROTOCOL_VERSION, __version__
from dramaclip.api import build_router
from dramaclip.api.agent_gateway import AgentGateway
from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis.runtime import AnalysisRuntime
from dramaclip.engines.tts.engines import indextts2
from dramaclip.infra import config, gpu, jobs, paths
from dramaclip.infra import logging as logging_setup
from dramaclip.infra.model_manager import cuda_runtime, registry
from dramaclip.infra.storage import backup, db
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.connection import ServiceConnection
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import (
    PARSE_ERROR,
    Router,
    RpcRequest,
    error_response,
)

_STOP_POLL_SECONDS = 1.0



_QUERY_PREFIXES = ("jobs.", "system.", "models.")

# 纯读查询显式清单（DB/内存级耗时）：专用小池成员，新增 RPC 必须二选一归类——
# tests/test_service_app_pool.py 用协议全覆盖钉死分类不缺号。
EXPLICIT_LIGHT_QUERIES = frozenset(
    {
        "analysis.results",
        "bgm.library",
        "bgm.runtime_status",
        "engine_configs.list",
        "export.get",
        "export.list",
        "export.list_works",
        "log.append",
        "narration.get_plan",
        "narration.list_plans",
        "narration.list_styles",
        "narration.llm_traces",
        "narration.plan_trace",
        "progress.update",
        "project.dashboard_summary",
        "project.get",
        "project.list",
        "prompts.list",
        "settings.get",
        "subtitle.list_presets",
    }
)


def _is_light_query(method: str) -> bool:
    """轻量查询走专用小池：列表/状态/get 类永不因长任务占满工作池而饿死。

    两次实锤（jobs.list、models.list 被批量长任务饿到客户端超时）后改为
    显式清单+模式兜底；新 RPC 未归类会被协议全覆盖测试拦下。
    """
    return (
        method in EXPLICIT_LIGHT_QUERIES
        or method.startswith(_QUERY_PREFIXES)
        or method.endswith(".status")
    )


class ServiceApp:
    """单实例服务。run() 阻塞直到 shutdown/EOF/SIGTERM，返回进程退出码。"""

    def __init__(
        self, address: str, token: str, data_dir_env: dict[str, str] | None = None
    ) -> None:
        self._address = address
        self._token = token
        self._data_dir_env = data_dir_env
        self._stop = threading.Event()
        self._connection: ServiceConnection | None = None

    def run(self) -> int:
        data_dir = paths.resolve_data_dir(self._data_dir_env)
        try:
            backup.backup_database(paths.db_path(data_dir))
        except sqlite3.Error as exc:  # 备份失败不阻塞启动
            print(f"[backup] 备份失败: {exc}")
        conn = db.connect(paths.db_path(data_dir))
        db.migrate(conn)
        cuda_runtime.inject_dll_dirs(data_dir)
        settings = config.load(conn)
        job_store = jobs.JobStore(conn)
        interrupted = job_store.sweep_interrupted()
        stale_episodes = episodes_repo.reset_stale_analyzing(conn)
        stale_exports = exports_repo.reset_stale_pending(conn)
        stale_projects = projects_repo.reset_stale_analyzing(conn)
        if interrupted or stale_episodes or stale_exports or stale_projects:
            print(
                f"[startup] 清扫上次会话残留：中断任务 {interrupted} 个，"
                f"分析中集 {stale_episodes} 个，未完成导出 {stale_exports} 个，"
                f"分析中项目 {stale_projects} 个"
            )
        gpu.prefetch()  # GPU 探测慢（nvidia-smi），启动即后台预热，health 不阻塞
        # 模型库状态/体积缓存预热（同 gpu.prefetch 模式）：placement 树首触扫描在冷盘
        # 环境是十秒级（真机 2026-10-19），不预热则引擎中心首开必等一次
        threading.Thread(
            target=registry.warm_caches,
            args=(data_dir / "models",),
            name="model-warm",
            daemon=True,
        ).start()

        log_file = logging_setup.setup_file_logging(data_dir / "logs")
        if log_file is not None:
            print(f"[logging] 服务日志: {log_file}")
        notifier = Notifier(self._send)
        work_dir = data_dir / "cache" / "analysis"
        work_dir.mkdir(parents=True, exist_ok=True)
        # +2 余量：长任务占满并发额度时，status/ping 类查询仍可执行；查询另走
        # 专用小池（2026-10-28 实测立案：批量重掷时规划链分钟级同步调用把池占满，
        # jobs.list 排队到客户端超时——「任务状态取不到」）
        workers = config.get_int(settings, "hardware.max_parallel_jobs") + 2
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        query_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rpc-query")

        # 线程看门狗（T1 诊断）：每 60s 把全线程调用栈写入 stderr——服务僵死时
        # 栈转储直接在客户端日志里可读，不再需要外部调试器附加。
        _wd_stop = threading.Event()

        def _thread_watchdog() -> None:
            import sys as _sys
            while not _wd_stop.wait(60):
                buf = io.StringIO()
                faulthandler.dump_traceback(file=buf)
                print(f"[watchdog] thread dump:\n{buf.getvalue()}", file=_sys.stderr, flush=True)

        _wd_thread = threading.Thread(target=_thread_watchdog, name="thread-watchdog", daemon=True)
        _wd_thread.start()
        context = AppContext(
            conn=conn,
            settings=settings,
            notifier=notifier,
            executor=executor,
            job_store=job_store,
            analysis_runtime=AnalysisRuntime(settings, data_dir / "models", data_dir),
            work_dir=work_dir,
            data_dir=data_dir,
        )
        router = build_router(context, self._shutdown)
        # Agent 网关：agent_gateway.enabled=true 时随服务常驻本机端口；settings.update 热生效
        gateway = AgentGateway(conn, trace_dir=llm_trace_dir(context))
        context.gateway = gateway
        if (state := gateway.sync(settings)) is not None:
            print(f"[agent-gateway] {state}")
        self._install_signal_handlers()
        try:
            self._serve(router, executor, query_executor)
            if interrupted or stale_episodes or stale_exports:
                notifier.log(
                    "warn",
                    "恢复上次会话："
                    f"{interrupted} 个中断任务、{stale_episodes} 个分析中集、"
                    f"{stale_exports} 个未完成导出已复位",
                )
            while not self._stop.is_set():
                self._stop.wait(_STOP_POLL_SECONDS)
        finally:
            executor.shutdown(wait=True)
            # 先等作业收尾再收 worker：合成中的段先落完，避免最后一问没有应答；
            # 常驻 worker 不收会在 Windows 上留占着模型内存的孤儿进程
            indextts2.shutdown_worker()
            from dramaclip.infra.model_manager import worker_bridge

            worker_bridge.shutdown_venv_workers()
            gateway.stop()
            if self._connection is not None:
                self._connection.close()
            conn.close()
        return 0

    def _serve(
        self,
        router: Router,
        executor: ThreadPoolExecutor,
        query_executor: ThreadPoolExecutor,
    ) -> None:
        self._connection = ServiceConnection(
            self._address,
            on_message=lambda payload: self._on_message(payload, router, executor, query_executor),
            on_disconnect=self._shutdown,
        )
        self._connection.send(self._hello_payload())
        self._connection.start_reader()

    def _hello_payload(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "token": self._token,
            "service_version": __version__,
            "protocol_version": PROTOCOL_VERSION,
        }

    def _send(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            return
        try:
            self._connection.send(payload)
        except (OSError, ValueError):
            self._shutdown()  # 下行失败视为连接已死，退出由主进程重新拉起

    def _on_message(
        self,
        payload: dict[str, Any],
        router: Router,
        executor: ThreadPoolExecutor,
        query_executor: ThreadPoolExecutor,
    ) -> None:
        if payload.get("type") == "hello-ack":
            return  # 主进程对握手的确认
        if not isinstance(payload.get("method"), str):
            self._send(error_response(None, PARSE_ERROR, "缺少 method 字段").model_dump())
            return
        try:
            request = RpcRequest.model_validate(payload)
        except ValueError as exc:
            self._send(error_response(None, PARSE_ERROR, f"请求解析失败: {exc}").model_dump())
            return
        if request.method == "system.ping":
            # 心跳快路径：读线程内联执行。执行池被长任务占满时若 ping 也排队，
            # Electron 会因心跳饿死判失联并 kill 本进程（真实事故）。
            self._send(router.dispatch(request).model_dump(exclude_none=True))
            return
        pool = query_executor if _is_light_query(request.method) else executor
        pool.submit(self._dispatch_and_reply, router, request)

    def _dispatch_and_reply(self, router: Router, request: RpcRequest) -> None:
        response = router.dispatch(request)
        self._send(response.model_dump(exclude_none=True))

    def _shutdown(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_args: self._shutdown())
