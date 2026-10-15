"""火山引擎 TTS（豆包语音 V1 HTTP 非流式）：无本地模型，按量计费。

凭证约定与火山 ASR 同构：`appid:token`（语音控制台 AppID 与 Access Token）。
V1 接口一次请求返回完整 wav；「模型」字段承载 cluster（默认 volcano_tts 大模型
音色域）。V1 不支持 2.0 代音色（那批要 V3 流式接口），音色表只收 V1 可用名单。
接口依据火山官方文档（豆包语音·大模型语音合成 HTTP 非流式 V1）。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from dramaclip.engines.tts.base import EngineCaps

_HOST = "https://openspeech.bytedance.com"
_PATH = "/api/v1/tts"
_DEFAULT_VOICE = "zh_female_cancan_mars_bigtts"
_DEFAULT_CLUSTER = "volcano_tts"
# V1 接口对单次文本的硬上限：1024 字节（UTF-8），官方建议 <300 字符
_MAX_TEXT_BYTES = 1024
_SUCCESS_CODE = 3000


class VolcTtsEngine:
    """V1 HTTP 非流式合成：一次 POST 返回 base64 wav，落盘即用。"""

    def __init__(self, api_key: str, model: str = "") -> None:
        key = api_key.strip()
        if key == "":
            raise ValueError(
                "火山引擎 TTS（云端）需要 API Key：请在引擎中心填写 tts.api_key"
            )
        self._api_key = key
        self._cluster = model.strip() or _DEFAULT_CLUSTER

    @property
    def name(self) -> str:
        return f"volc_tts:{self._cluster}"

    def capabilities(self) -> EngineCaps:
        return EngineCaps(
            sample_rate=24000,  # V1 默认输出采样率（可传 8000/16000 降档，不做）
            supports_cloning=True,  # voice 传控制台克隆音色 id 即用
            supports_emotion=False,
            speed_control="none",
            available=True,  # 构造成功即视为可用（Key 在构造期已校验非空）
            reason="云端可达（火山引擎，按量计费）",
        )

    def is_available(self) -> tuple[bool, str]:
        return True, "云端可达（火山引擎，按量计费）"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        appid, token = self._credentials()
        if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
            raise ValueError("火山 TTS 单次合成文本超出 1024 字节上限：请拆短该句后重试")
        payload = json.dumps({
            # app.token 是文档示例的固定值（鉴权实际靠 Authorization 头，此字段无实效）
            "app": {"appid": appid, "token": "access_token", "cluster": self._cluster},
            "user": {"uid": "dramaclip"},
            "audio": {"voice_type": voice.strip() or _DEFAULT_VOICE, "encoding": "wav"},
            "request": {"reqid": uuid4().hex, "text": text, "operation": "query"},
        }).encode()
        request = urllib.request.Request(
            f"{_HOST}{_PATH}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                # 火山 V1 鉴权是分号格式（Bearer;token），不是标准「Bearer 空格」
                "Authorization": f"Bearer;{token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"火山 TTS 请求失败 HTTP {exc.code}: {detail}") from exc
        code = int(body.get("code", -1))
        if code != _SUCCESS_CODE:
            raise RuntimeError(f"火山 TTS 合成失败 {code}: {body.get('message')}")
        audio = base64.b64decode(str(body.get("data", "")))
        if audio == b"":
            raise RuntimeError("火山 TTS 合成返回空音频")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
        target.write_bytes(audio)
        return target

    def _credentials(self) -> tuple[str, str]:
        if ":" not in self._api_key:
            raise ValueError(
                "火山引擎 TTS 需要双凭证：API Key 填 `appid:token`"
                "（火山引擎语音控制台的 AppID 与 Access Token，冒号分隔）"
            )
        appid, _, token = self._api_key.rpartition(":")
        if appid == "" or token == "":
            raise ValueError("火山引擎 TTS 凭证格式应为 `appid:token`（两段都要有值）")
        return appid, token
