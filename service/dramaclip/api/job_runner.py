"""线程化作业的统一启动壳：create→running→线程跑 work→看门狗收尾。

models 域六处安装/导入作业各自手写同一套双线程骨架（2026-11-26 普查：六个
``_watch`` 闭包四个逐字相同），收敛到这一处后，「终态怎么落、取消登记怎么
回收」只有一份答案。模型下载（``download``）是特形——下载器自管线程、结局
由回报决定——不套这个壳。

work 的契约：跑完返回**完成话术**（运行器记 info 日志），失败抛异常（由
``failure_message`` 转成作业 error，默认原样）。进度由 work 自己经
``job_store.set_progress`` 汇报。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.jobs import STATUS_RUNNING


def launch_threaded_job(
    context: AppContext,
    *,
    job_type: str,
    ref_id: str,
    work: Callable[[str, threading.Event], str | None],
    failure_message: Callable[[Exception], str] = str,
    cancellable: bool = True,
    on_settled: Callable[[], None] | None = None,
    thread_prefix: str = "",
) -> str:
    """起一个线程化作业并返回 job_id。

    - ``work(job_id, cancel_event)``：阻塞体。正常返回即成功（返回值是完成
      话术，None 静默）；抛异常按 ``failure_message(exc)`` 落 error。成功话术
      的 ``notifier.log`` 也在 try 内——通知通道坏了同样按作业失败落账，
      不让线程无声死掉把 done_event 永远悬着。
    - ``cancellable=False``：不注册 ``cancel_events``（复制半途没有「撤销」
      可言的作业用），看门狗也不回收。
    - ``on_settled``：终态落定后必跑（成败都跑），如模型库缓存失效。
    - 看门狗只给仍 ``running`` 的作业补 completed：work 自己落过终态的不再动。
    """
    job_id = context.job_store.create(job_type, ref_id=ref_id)
    # 必须置 running：看门狗的回写条件是 status==running，启动清扫也只扫
    # running——不置位则成功后记录永远停在 pending，重启也清不掉。
    context.job_store.mark_running(job_id)
    cancel_event = threading.Event()
    if cancellable:
        context.cancel_events[job_id] = cancel_event
    done_event = threading.Event()

    def _run() -> None:
        try:
            message = work(job_id, cancel_event)
            if message:
                context.notifier.log("info", message)
        except Exception as exc:  # noqa: BLE001 - 作业失败原样落 error
            context.job_store.mark_failed(job_id, failure_message(exc))
        finally:
            done_event.set()

    def _watch() -> None:
        done_event.wait()
        job = context.job_store.get(job_id)
        if job is not None and job["status"] == STATUS_RUNNING:
            context.job_store.mark_completed(job_id)
        if cancellable:
            context.cancel_events.pop(job_id, None)
        if on_settled is not None:
            on_settled()

    prefix = thread_prefix or job_type
    threading.Thread(target=_run, daemon=True, name=prefix).start()
    threading.Thread(target=_watch, daemon=True, name=f"{prefix}-watch").start()
    return job_id


def first_active_job(context: AppContext, job_type: str) -> dict[str, Any] | None:
    """同型作业串行闸的查询半边：还有在跑的同一类型就返回它（话术留在调用点）。"""
    active = [
        job
        for job in context.job_store.list_recent(limit=50, active_only=True)
        if job["type"] == job_type
    ]
    return active[0] if active else None
