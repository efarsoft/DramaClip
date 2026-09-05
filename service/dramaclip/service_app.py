"""服务装配：存储初始化、路由、执行池与连接生命周期（docs/service/00 启动时序）。"""

from __future__ import annotations

import signal
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from dramaclip import PROTOCOL_VERSION, __version__
from dramaclip.api import build_router
from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.runtime import AnalysisRuntime
from dramaclip.infra import config, jobs, paths
from dramaclip.infra.storage import backup, db
from dramaclip.transport.connection import ServiceConnection
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import (
    PARSE_ERROR,
    Router,
    RpcRequest,
    error_response,
)

_STOP_POLL_SECONDS = 1.0


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
        settings = config.load(conn)
        job_store = jobs.JobStore(conn)
        interrupted = job_store.sweep_interrupted()

        notifier = Notifier(self._send)
        work_dir = data_dir / "cache" / "analysis"
        work_dir.mkdir(parents=True, exist_ok=True)
        # +2 余量：长任务占满并发额度时，status/ping 类查询仍可执行
        workers = config.get_int(settings, "hardware.max_parallel_jobs") + 2
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        context = AppContext(
            conn=conn,
            settings=settings,
            notifier=notifier,
            executor=executor,
            job_store=job_store,
            analysis_runtime=AnalysisRuntime(settings, data_dir / "models"),
            work_dir=work_dir,
        )
        router = build_router(context, self._shutdown)
        self._install_signal_handlers()
        try:
            self._serve(router, executor)
            if interrupted:
                notifier.log("warn", f"恢复上次会话：{interrupted} 个中断任务已标记失败")
            while not self._stop.is_set():
                self._stop.wait(_STOP_POLL_SECONDS)
        finally:
            executor.shutdown(wait=True)
            if self._connection is not None:
                self._connection.close()
            conn.close()
        return 0

    def _serve(self, router: Router, executor: ThreadPoolExecutor) -> None:
        self._connection = ServiceConnection(
            self._address,
            on_message=lambda payload: self._on_message(payload, router, executor),
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
        self, payload: dict[str, Any], router: Router, executor: ThreadPoolExecutor
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
        executor.submit(self._dispatch_and_reply, router, request)

    def _dispatch_and_reply(self, router: Router, request: RpcRequest) -> None:
        response = router.dispatch(request)
        self._send(response.model_dump(exclude_none=True))

    def _shutdown(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_args: self._shutdown())
