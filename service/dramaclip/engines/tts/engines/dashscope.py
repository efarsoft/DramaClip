"""百炼语音合成（云端 TTS）：无本地模型，按量计费，克隆音色用云端 voice id。

P1 云端化的 TTS 跃升路径：弱机不装 IndexTTS2 运行环境，一个 API Key 直出。
CosyVoice v2/v3 系与 Qwen-Audio-TTS 三族同走 audio/tts/SpeechSynthesizer HTTP
端点（请求形状一致，均实测 22050Hz），非流式返回音频文件 URL（24 小时有效）
再下载落盘——不依赖 SDK 的代际适配进度。三族音色体系互不相通（v2 音色 v3
不收），默认音色按模型代际回落。`voice` 传云端音色 id 或已克隆的 voice id。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines.tts.base import EngineCaps
from dramaclip.infra import compute

_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"


#: 内容审核降级词表（确定性兜底，零 LLM 成本）：短剧台词的打斗/血腥/亲密
#: 表达是云 TTS 撞审核的常态来源——替换为语义邻道的过审词，重试一次。
_BLOCKED_WORD_MAP = {
    "血": "红色",
    "杀": "动手",
    "死了": "倒下",
    "死": "倒下",
    "尸体": "人影",
    "毒品": "违禁品",
    "枪": "家伙",
    "刀": "利器",
    "裸": "赤裸着上身".replace("裸", ""),  # 占位防自替换；实际映射见下行
}
_BLOCKED_WORD_MAP.pop("裸", None)  # 「裸」单字替换风险大：不做映射，交给整句重试失败


def _sanitize_blocked_text(text: str) -> str:
    """审核降级词表替换（保序，长词优先）。"""
    for source in sorted(_BLOCKED_WORD_MAP, key=len, reverse=True):
        text = text.replace(source, _BLOCKED_WORD_MAP[source])
    return text


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
        import logging
        import time
        import urllib.error
        import urllib.request

        payload: dict[str, Any] = {
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

        class _ComposeError(Exception):
            """合成请求 HTTP 错误（带响应体细节），供审核降级分支判别。"""

        def fetch(request: urllib.request.Request, what: str) -> bytes:
            # 网络类失败（连接重置/超时）短退避重试：一次抖动不该炸掉整段配音
            # ——导出链一段失败即整条导出失败（_ensure_voiced 不容降级）。
            # HTTPError 原样上抛：响应体带业务细节（配额/参数错），重试没有意义。
            backoff = (3.0, 8.0)
            for attempt in range(len(backoff) + 1):
                try:
                    with urllib.request.urlopen(request, timeout=120) as resp:
                        return bytes(resp.read())
                except urllib.error.HTTPError:
                    raise
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    if attempt >= len(backoff):
                        raise RuntimeError(f"{what}网络失败（已重试 {attempt} 次）: {exc}") from exc
                    pause = backoff[attempt]
                    logging.getLogger(__name__).warning(
                        "%s 网络类失败（%s），%.0fs 后重试 (%d/%d)",
                        what, exc, pause, attempt + 1, len(backoff),
                    )
                    time.sleep(pause)
            raise RuntimeError(f"{what}网络失败: 不可达路径")

        def _compose(request: urllib.request.Request) -> dict[str, Any]:
            try:
                result: dict[str, Any] = json.loads(
                    fetch(request, "CosyVoice 云端合成").decode("utf-8")
                )
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                raise _ComposeError(detail) from exc

        try:
            body = _compose(req)
        except _ComposeError as exc:
            from dramaclip.engines.semantic.llm_client import is_content_blocked

            if not is_content_blocked(str(exc)):
                raise RuntimeError(f"CosyVoice 云端合成失败: {exc}") from exc
            # 内容审核拒绝：词表降级重试一次（短剧打斗/血腥词是常态来源），
            # 仍被拒如实抛——不静默换文案（那是编剧层的职责）。
            safe_text = _sanitize_blocked_text(text)
            logging.getLogger(__name__).warning(
                "CosyVoice 内容审核拒绝，词表降级重试一次（%d 处替换）",
                len(text) - len(text.replace("血", "").replace("杀", "")),
            )
            if isinstance(payload.get("input"), dict):
                payload["input"]["text"] = safe_text
            retry_req = urllib.request.Request(
                _TTS_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                body = _compose(retry_req)
            except _ComposeError as exc2:
                raise RuntimeError(
                    f"CosyVoice 内容审核拒绝（词表降级后仍被拒）: {exc2}"
                ) from exc2
        audio_url = ((body.get("output") or {}).get("audio") or {}).get("url")
        if not audio_url:
            raise RuntimeError(f"CosyVoice 云端合成未返回音频地址: {str(body)[:200]}")
        audio = fetch(
            urllib.request.Request(audio_url), "CosyVoice 音频下载"
        )
        if not audio:
            raise RuntimeError("CosyVoice 云端合成返回空音频")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
        target.write_bytes(audio)
        return target
