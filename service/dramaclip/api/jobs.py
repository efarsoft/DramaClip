"""jobs 命名空间：任务查询与统一取消（队列页数据源）。"""

from __future__ import annotations

import time
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.jobs import _TERMINAL_STATUSES
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_JOB_NOT_FOUND = -32501  # 任务域 -32500~-32599（见 common.json x-error-codes）

_LIMIT_MAX = 200  # 与 protocol/schemas/jobs.json 的 params.limit.maximum 一致


def register(router: Router, context: AppContext) -> None:
    router.register("jobs.list", lambda params: list_jobs(context, params))
    router.register("jobs.get", lambda params: get_job(context, params))
    router.register("jobs.cancel", lambda params: cancel(context, params))


def list_jobs(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """跨类型任务列表，按最近变更倒序。"""
    # 双向钳制，与 params schema 的 minimum/maximum 一致（Router 不做 schema 校验）：
    # 只钳上限时，负数会原样进 SQL——SQLite 的负 LIMIT 语义是「不限量」。
    limit = max(min(int(params.get("limit", 50)), _LIMIT_MAX), 1)
    active_only = bool(params.get("active_only", False))
    return {
        "jobs": context.job_store.list_recent(limit=limit, active_only=active_only),
        "server_time_ms": _now_ms(),
    }


def get_job(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    return {"job": job}


def cancel(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """按 job_id 请求取消；任务自己在下个检查点退出并标 cancelled。"""
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    # 终态集直接复用 infra/jobs 的 _TERMINAL_STATUSES：本文件另写一份字面量会与
    # JobStore._transition 的校验各跑各的，将来加一个状态就漏一处。
    if job["status"] in _TERMINAL_STATUSES:
        return {"job_id": job_id, "cancelling": False, "reason": "任务已终态"}
    event = context.cancel_events.get(job_id)
    if event is None:
        # 没有可中断入口（注册表按 job_id 存事件，收尾时 pop）：如实回不可中断，
        # 绝不能谎报「已取消」。如 model_download 下载结束后事件已被看门狗回收。
        return {"job_id": job_id, "cancelling": False, "reason": "任务不可中断"}
    event.set()
    context.notifier.log("info", f"已请求取消：{job['type']} {job.get('label') or job_id}")
    return {"job_id": job_id, "cancelling": True}


def _now_ms() -> int:
    return int(time.time() * 1000)
