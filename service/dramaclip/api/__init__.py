"""RPC 方法注册层（transport ↔ engines 粘合）。文件 = 命名空间（docs/service/01 第 4 节）。"""

from __future__ import annotations

from collections.abc import Callable

from dramaclip import PROTOCOL_VERSION, __version__
from dramaclip.transport.rpc import Router


def build_router(shutdown: Callable[[], None]) -> Router:
    """组装全部命名空间。新增命名空间在此登记 import 与 register。"""
    from dramaclip.api import system

    router = Router()
    system.register(
        router,
        service_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        shutdown=shutdown,
    )
    return router
