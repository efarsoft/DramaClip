"""百炼语音合成（云端 TTS）：无本地模型，按量计费，克隆音色用云端 voice id。

P1 云端化的 TTS 跃升路径：弱机不装 IndexTTS2 运行环境，一个 API Key 直出。
CosyVoice v2/v3 系与 Qwen-Audio-TTS 三族同走 audio/tts/SpeechSynthesizer HTTP
端点（请求形状一致，均实测 22050Hz），非流式返回音频文件 URL（24 小时有效）
再下载落盘——不依赖 SDK 的代际适配进度。三族音色体系互不相通（v2 音色 v3
不收），默认音色按模型代际回落。`voice` 传云端音色 id 或已克隆的 voice id。
"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.tts.base import EngineCaps
from dramaclip.infra import compute

_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"


def _default_voice(model: str) -> str:
    """模型代际 → 默认音色（三族音色体系互不相通，各自取官方标杆音色）。"""
    if model.startswith("qwen-audio"):
        return "longanhuan_v3.6"
    if "v3" in model:
        return "longanyang"
    return "longxiaochun_v2"


class DashscopeCosyVoiceEngine:
    """百炼云端合成（CosyVoice v2/v3 系与 Qwen-Audio-TTS 同引擎）：HTTP 直连。"""

    def __init__(self, api_key: str, model: str = "cosyvoice-v2") -> None:
        key = api_key.strip()
        if key == "":
            raise ValueError(
                "CosyVoice 云端（百炼）需要 API Key：请在引擎中心填写 tts.api_key"
            )
        self._api_key = key
        self._model = model

    @property
    def name(self) -> str:
        return f"cosyvoice_cloud:{self._model}"

    def capabilities(self) -> EngineCaps:
        return EngineCaps(
            # 量自 dashscope AudioFormat.WAV_22050HZ_MONO_16BIT
            sample_rate=22050,
            supports_cloning=True,  # voice 传云端克隆音色 id 即用
            supports_emotion=False,
            speed_control="none",
            available=True,  # 构造成功即视为可用（Key 在构造期已校验非空）
            reason="云端可达（百炼，按量计费）",
        )

    def is_available(self) -> tuple[bool, str]:
        # HTTP 直连只需标准库，Key 在构造期已校验非空
        return True, "云端可达（百炼，按量计费）"

    def compute(self) -> compute.ComputeReport:
        return compute.cloud("tts.cosyvoice_cloud")

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import json
        import urllib.error
        import urllib.request

        payload = {
            "model": self._model,
            "input": {
                "text": text,
                "voice": voice.strip() or _default_voice(self._model),
                "format": "wav",
                "sample_rate": 22050,
            },
        }
        req = urllib.request.Request(
            _TTS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"CosyVoice 云端合成失败: {detail}") from exc
        audio_url = ((body.get("output") or {}).get("audio") or {}).get("url")
        if not audio_url:
            raise RuntimeError(f"CosyVoice 云端合成未返回音频地址: {str(body)[:200]}")
        with urllib.request.urlopen(audio_url, timeout=120) as audio_resp:
            audio = audio_resp.read()
        if not audio:
            raise RuntimeError("CosyVoice 云端合成返回空音频")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
        target.write_bytes(audio)
        return target
