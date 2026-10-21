"""算力回执：请求归一、报告不变量、显式 CUDA 失败的统一异常。

引擎不各拼一套 JSON：`auto` 才允许试 GPU 后回退，显式 `cuda` 是承诺。
`actual` 允许视频编码器名（nvenc/amf/qsv/libx264），不局限在设备三元组；视频编码
的段级回退是既有的可用性保护，允许发生但必须带原因、落在 libx264 且可见。
分离的 DirectML 通道：`requested` 词汇不变（auto/cuda/cpu），`resolved/actual`
允许 `"dml"`——它是解析结果不是请求项，显式 cuda 落 dml 照样判违约。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_REQUESTED = frozenset({"auto", "cuda", "cpu"})


class ComputeUnavailableError(RuntimeError):
    """请求的算力不可用（显式 cuda 失败、或成功路径的实际设备违约）。"""


def normalize_requested(value: str | None) -> str:
    requested = (value or "auto").strip().lower()
    if requested not in _REQUESTED:
        raise ValueError(f"未知算力请求: {value!r}（可用: auto / cuda / cpu）")
    return requested


@dataclass(frozen=True)
class ComputeReport:
    component: str
    requested: str = "auto"
    resolved: str = "cpu"
    actual: str = "unknown"
    fallback: bool = False
    reason: str = ""
    device: str = ""

    def __post_init__(self) -> None:
        if not self.component or not self.resolved or not self.actual:
            raise ValueError("compute 回执的 component/resolved/actual 不能为空")
        if self.requested not in _REQUESTED:
            raise ValueError(f"未知算力请求: {self.requested!r}")
        if self.fallback and not self.reason.strip():
            raise ValueError("fallback=true 必须带原因")
        if self.fallback and self.component == "video.encode":
            # 视频回退的单位是编码器而不是设备：硬编段失败后整片重跑 libx264。
            # 显式硬编也可能走到这里（段级可用性保护不取消），但必须可见。
            if (
                self.requested not in {"auto", "cuda"}
                or self.actual != "libx264"
                or self.resolved == self.actual
            ):
                raise ValueError("video.encode 的 fallback 只表示硬编失败后整片重跑 libx264")
        elif self.fallback and (
            self.requested != "auto"
            or self.resolved not in ("cuda", "dml")
            or self.actual != "cpu"
        ):
            raise ValueError("fallback=true 只表示 auto 下试过 GPU 后落 CPU，且必须带原因")
        if self.requested == "cpu" and self.resolved in ("cuda", "dml"):
            raise ValueError("requested=cpu 不得解析到 GPU 后端")
        if not self.device:
            object.__setattr__(self, "device", self.actual)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def remember(report: ComputeReport) -> dict[str, Any]:
    return report.to_dict()


def assert_success(report: ComputeReport) -> None:
    """成功路径的最后一道防假绿：unknown / 显式 cuda 落 CPU 都判违约。"""
    if report.actual == "unknown":
        raise ComputeUnavailableError(
            f"{report.component} 成功路径没有实际设备证据（actual=unknown）"
        )
    if report.component == "video.encode":
        if report.requested == "cpu" and report.actual != "libx264":
            raise ComputeUnavailableError(
                f"{report.component} 请求 cpu，实际 {report.actual}"
            )
        if report.actual != report.resolved and not report.fallback:
            raise ComputeUnavailableError(
                f"{report.component} 实际编码器 {report.actual} 与解析 {report.resolved} 不一致，"
                "且没有回退记录"
            )
        return
    if report.actual == "cloud":
        return  # 云端忽略本地设备请求，不算回退也不受 cuda 承诺约束
    if report.requested == "cuda" and report.actual != "cuda":
        raise ComputeUnavailableError(
            f"{report.component} 请求 cuda，实际 {report.actual}：{report.reason or '无原因'}"
        )
    if report.requested == "cpu" and report.actual not in {"cpu", "cloud"}:
        raise ComputeUnavailableError(
            f"{report.component} 请求 cpu，实际 {report.actual}"
        )


def cloud(component: str, requested: str = "auto") -> ComputeReport:
    return ComputeReport(
        component=component, requested=normalize_requested(requested),
        resolved="cloud", actual="cloud",
    )


def unsupported(component: str, requested: str, reason: str) -> ComputeReport:
    return ComputeReport(
        component=component, requested=normalize_requested(requested),
        resolved="cpu", actual="cpu", reason=reason,
    )
