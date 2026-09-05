"""Edge TTS 引擎：微软云端免费合成，无需本地模型（依赖准入：edge-tts，纯 Python）。

同步封装：edge-tts 为 asyncio 库，在线程内 asyncio.run 执行。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dramaclip.engines.tts.base import DEFAULT_VOICE


class EdgeTtsEngine:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(2)

    @property
    def name(self) -> str:
        return "edge"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import edge_tts  # 可选依赖懒加载

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice or DEFAULT_VOICE)
            await communicate.save(str(out_path))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(_run())
        return out_path
