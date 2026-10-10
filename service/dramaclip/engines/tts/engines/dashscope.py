"""百炼 CosyVoice-v2（云端 TTS）：无本地模型，按量计费，克隆音色用云端 voice id。

P1 云端化的 TTS 跃升路径：弱机不装 IndexTTS2 运行环境，一个 API Key 直出。
音色约定：`voice` 传云端音色 id（如 longxiaochun_v2）或已克隆的 voice id；
空值回落引擎默认音色。参考音频的云端克隆走百炼控制台/接口，本引擎只消费 id。
"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.tts.base import EngineCaps

_DEFAULT_VOICE = "longxiaochun_v2"


class DashscopeCosyVoiceEngine:
    """CosyVoice-v2（DashScope 同步合成）：`call` 一次返回完整音频字节。"""

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
        import importlib.util

        if importlib.util.find_spec("dashscope") is None:
            return False, "未装运行环境：缺 dashscope 依赖（pip install dashscope）"
        return True, "云端可达（百炼，按量计费）"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

        synthesizer = SpeechSynthesizer(
            model=self._model,
            voice=voice.strip() or _DEFAULT_VOICE,
            format=AudioFormat.WAV_22050HZ_MONO_16BIT,
        )
        audio = synthesizer.call(text)
        if not audio:
            raise RuntimeError("CosyVoice 云端合成返回空音频")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
        target.write_bytes(audio)
        return target
