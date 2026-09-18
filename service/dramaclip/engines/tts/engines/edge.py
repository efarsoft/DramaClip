"""Edge TTS 引擎：微软云端免费合成，无需本地模型（依赖准入：edge-tts，纯 Python）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dramaclip.engines.tts.base import DEFAULT_VOICE

SYNTH_TIMEOUT_S = 45.0


class EdgeTtsTimeout(TimeoutError):
    """edge-tts 合成超时（网络不佳/服务不可达）。"""


class EdgeTtsEngine:
    @property
    def name(self) -> str:
        return "edge"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import edge_tts  # 可选依赖懒加载

        async def _run() -> None:
            # 非 Edge 音色名（如升级前全局键残留的 Kokoro 名）回退默认，避免云端报错
            safe_voice = voice if voice.startswith("zh-") else DEFAULT_VOICE
            communicate = edge_tts.Communicate(text, safe_voice)
            await communicate.save(str(out_path))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(asyncio.wait_for(_run(), timeout=SYNTH_TIMEOUT_S))
        except TimeoutError as exc:
            out_path.unlink(missing_ok=True)
            raise EdgeTtsTimeout(f"edge-tts 合成超时({SYNTH_TIMEOUT_S:.0f}s)") from exc
        return out_path
