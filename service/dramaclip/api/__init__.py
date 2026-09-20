"""RPC 方法注册层（transport ↔ engines 粘合）。文件 = 命名空间（docs/service/01 §4）。"""

from __future__ import annotations

from collections.abc import Callable

from dramaclip import PROTOCOL_VERSION, __version__
from dramaclip.api.context import AppContext
from dramaclip.transport.rpc import Router


def build_router(context: AppContext, shutdown: Callable[[], None]) -> Router:
    """组装全部命名空间。新增命名空间在此登记 import 与 register。"""
    from dramaclip.api import (
        analysis,
        engine_configs,
        export,
        jobs,
        models,
        narration,
        project,
        prompts,
        settings,
        subtitle,
        system,
        tts,
    )

    router = Router()
    system.register(
        router,
        service_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        shutdown=shutdown,
    )
    project.register(router, context)
    prompts.register(router, context)
    analysis.register(router, context)
    narration.register(router, context)
    export.register(router, context)
    settings.register(router, context)
    engine_configs.register(router, context)
    subtitle.register(router)
    tts.register(router, context)
    models.register(router, context)
    jobs.register(router, context)
    return router
