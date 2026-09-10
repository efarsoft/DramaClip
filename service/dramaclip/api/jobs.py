"""jobs 命名空间：任务查询（队列页数据源）。取消在 Task 4 加入。"""

from __future__ import annotations

import time
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_JOB_NOT_FOUND = -32404  # 落在 x-error-codes 的 -32400~-32499 导出域段（Task 4 复用同值）

_LIMIT_MAX = 200  # 与 protocol/schemas/jobs.json 的 params.limit.maximum 一致


def register(router: Router, context: AppContext) -> None:
    router.register("jobs.list", lambda params: list_jobs(context, params))
    router.register("jobs.get", lambda params: get_job(context, params))


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


def _now_ms() -> int:
    return int(time.time() * 1000)
