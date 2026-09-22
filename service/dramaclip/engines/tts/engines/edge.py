"""Edge TTS 引擎：微软云端免费合成，无需本地模型（依赖准入：edge-tts，纯 Python）。
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
from pathlib import Path

from dramaclip.engines.tts.base import DEFAULT_VOICE, EngineCaps
from dramaclip.engines.tts.text_split import split_long_text

SYNTH_TIMEOUT_S = 45.0

#: 长文本切块上限（text_split 对 CJK 文本自动用 200，latin 用 500）。
#: edge 服务端对超长单请求会自行再切且易触发 45s 超时，客户端先切更稳。
#: 分块 mp3 直接按字节序拼接：各块同格式（audio-24khz-48kbitrate-mono-mp3，
#: CBR 无帧头依赖），播放器按流解码，块边界无爆音；实测口径见 text_split 注释。
_CLOUD_HOST = ("speech.platform.bing.com", 443)
_CLOUD_PROBE_TIMEOUT_S = 5.0


def _cloud_reachable() -> bool:
    """TCP 连通性探测：只测到云端合成服务的握手，不发合成请求（不花钱不触内容审核）。"""
    try:
        with socket.create_connection(_CLOUD_HOST, timeout=_CLOUD_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


class EdgeTtsTimeout(TimeoutError):
    """edge-tts 合成超时（网络不佳/服务不可达）。"""


class EdgeTtsEngine:
    @property
    def name(self) -> str:
        return "edge"

    def capabilities(self) -> EngineCaps:
        available, reason = self.is_available()
        return EngineCaps(
            # 量自 edge_tts/communicate.py：outputFormat=audio-24khz-48kbitrate-mono-mp3
            sample_rate=24000,
            supports_cloning=False,  # 固定音色库，无参考音频入口
            supports_emotion=False,  # 音色自带风格，请求级情绪参数未开放
            # 量自 Communicate.__init__ 签名：rate: str = '+0%'（如 '+20%'）
            speed_control="native",
            available=available,
            reason=reason,
        )

    def is_available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("edge_tts") is None:
            return False, "未装运行环境：缺 edge-tts 依赖（pip install edge-tts）"
        try:
            reachable = _cloud_reachable()
        except OSError as exc:
            return False, f"云端不可达：{exc}"
        if not reachable:
            return False, "云端不可达：连不上 speech.platform.bing.com:443（检查网络）"
        return True, "云端可达"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import edge_tts  # 可选依赖懒加载

        async def _save(communicate: edge_tts.Communicate, path: Path) -> None:
            await asyncio.wait_for(communicate.save(str(path)), timeout=SYNTH_TIMEOUT_S)

        async def _run() -> None:
            # 非 Edge 音色名（如升级前全局键残留的 Kokoro 名）回退默认，避免云端报错
            safe_voice = voice if voice.startswith("zh-") else DEFAULT_VOICE
            chunks, dropped = split_long_text(text)
            if len(chunks) <= 1:
                # 单块（含 dropped=1 的全空白文本）：整段一次请求，走旧路径
                await _save(edge_tts.Communicate(text, safe_voice), out_path)
                return
            # 多块：逐块合成到临时目录，按序字节拼接——对调用方仍是单文件契约
            # （缓存 key 用切分前整段原文，见 base.TtsEngine.synthesize docstring）。
            parts_dir = out_path.parent / f".{out_path.stem}.parts"
            parts_dir.mkdir(parents=True, exist_ok=True)
            try:
                pieces: list[bytes] = []
                for index, chunk in enumerate(chunks):
                    part = parts_dir / f"part-{index:04d}.mp3"
                    await _save(edge_tts.Communicate(chunk, safe_voice), part)
                    pieces.append(part.read_bytes())
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"".join(pieces))
            finally:
                for part in parts_dir.glob("*"):
                    part.unlink(missing_ok=True)
                parts_dir.rmdir()
            if dropped:
                # 空块已丢弃并计数：诚实留痕，不静默（logger 而非 print，与管线日志同源）
                import logging

                logging.getLogger(__name__).info(
                    "edge 长文本切分丢弃 %d 个空块（%d 块合成）", dropped, len(chunks)
                )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(_run())
        except TimeoutError as exc:
            out_path.unlink(missing_ok=True)
            raise EdgeTtsTimeout(f"edge-tts 合成超时({SYNTH_TIMEOUT_S:.0f}s)") from exc
        return out_path
