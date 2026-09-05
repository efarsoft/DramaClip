"""时间线编辑（W13）：段选中/微调/删除后整轴替换回写 plan_data。

约束：起止须合法（end>start≥0）；相邻段允许重叠（导出按顺序拼接）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from dramaclip.api.context import AppContext
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PLAN_NOT_FOUND = -32401
_ERR_SEGMENT_INVALID = -32403


class SegmentInput(BaseModel):
    """前端回传的单段编辑结果。"""

    episode_id: str
    start: float = Field(ge=0)
    end: float
    audio: str = "original"
    transition: str = "cut"
    subtitle_text: str | None = None


class ReplaceTimelineInput(BaseModel):
    plan_id: str
    segments: list[SegmentInput] = Field(min_length=1)


def register(router: Router, context: AppContext) -> None:
    router.register(
        "narration.replace_timeline", lambda params: replace_timeline(context, params)
    )


def replace_timeline(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """整轴替换编排时间轴（前端编辑器保存）。"""
    try:
        payload = ReplaceTimelineInput.model_validate(params)
    except ValueError as exc:
        raise RpcDomainError(_ERR_SEGMENT_INVALID, f"参数无效: {exc}") from exc

    for segment in payload.segments:
        if segment.end <= segment.start:
            raise RpcDomainError(
                _ERR_SEGMENT_INVALID,
                f"段结束时间须大于开始时间（{segment.start}-{segment.end}）",
            )

    plan = plans_repo.get(context.conn, payload.plan_id)
    if plan is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {payload.plan_id}")

    plan_data = dict(plan["plan_data"])
    plan_data["timeline"] = [segment.model_dump() for segment in payload.segments]
    plans_repo.update_plan_data(
        context.conn, payload.plan_id, json.dumps(plan_data, ensure_ascii=False)
    )
    return {"ok": True, "count": len(payload.segments)}
