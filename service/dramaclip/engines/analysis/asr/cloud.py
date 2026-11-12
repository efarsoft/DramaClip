"""Dashscope 云端 ASR 引擎：百炼语音识别，同步切片，按音频时长计费。

自 transcriber.py 拆出（拆分专项）：云端引擎独立成模块，依赖 common
（_speaker_label）与 pause_split（能量停顿切分）。无本地模型、无 torch，
依赖最轻。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines.analysis import pause_split
from dramaclip.engines.analysis.asr.common import _LOGGER
from dramaclip.engines.analysis.diarize import _speaker_label
from dramaclip.engines.analysis.models import AsrSegment, WordSpan
from dramaclip.infra import compute


class DashscopeCloudAsrEngine:
    """百炼语音识别（云端，同步切片）：无本地模型，按音频时长计费。

    qwen-audio-3.1-asr-flash 走 DashScope 同步多模态端点——SDK 对 content
    里本地文件路径自动上传并在请求头开启 OssResourceResolve 解析，无
    filetrans「公网 URL 单收」死路。官方单次调用音频上限 5 分钟，整集 wav
    先按能量停顿切 ≤4 分钟片（pause_split 同一套基础设施），逐片同步转写
    后按片起点偏移合并。句级+字级时间戳固定开启；qwen-audio-3.1 系
    speaker_diarization_enabled 开说话人分离，说话人取字级 speaker_id
    （句级字段是聚合对象不可信）→ 角色A/B…，与本地聚类标签同格式。
    各片独立分离，跨片编号不保证对齐——已知局限。fun-asr 系无分离，
    说话人为 None。
    """

    # 单片上限：官方 5 分钟/次，切 4 分钟留合并与边界余量
    _CHUNK_S = 240.0

    # 只有这一族实测回传字级 speaker_id；fun-asr 系没有分离字段，要了也不会给
    _DIARIZED_MODEL_PREFIX = "qwen-audio-3.1"

    def __init__(
        self,
        api_key: str,
        model: str = "qwen-audio-3.1-asr-flash",
        diarization: bool = True,
    ) -> None:
        # Key 缺失不在构造期拦：所有已接线引擎必须能空载构造（wired 不变量），
        # 真正的调用在 transcribe 期按分档报错。
        self._api_key = api_key.strip()
        self._model = model
        self._diarization = diarization

    @property
    def name(self) -> str:
        return f"dashscope_cloud:{self._model}"

    @classmethod
    def supports_model(cls, model: str) -> bool:
        """按模型族判定分离能力——`asr.model` 能在工厂里换，声明就得跟着换。"""
        return model.startswith(cls._DIARIZED_MODEL_PREFIX)

    def compute(self) -> compute.ComputeReport | None:
        return compute.cloud("asr.cloud")

    @property
    def supports_diarization(self) -> bool:
        return self.supports_model(self._model)

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        import tempfile
        import wave

        from dashscope import MultiModalConversation

        if self._api_key == "":
            raise ValueError(
                "百炼语音识别（云端）需要 API Key：请在引擎中心填写 asr.api_key"
            )
        # language/hotwords 同步端点参数名未在官方示例中给出，如实不透传
        # （语种自动检测；热词待文档确认后接）
        with wave.open(str(wav_path), "rb") as wf:
            sample_rate = wf.getframerate()
        chunks = self._chunks(wav_path)
        segments: list[AsrSegment] = []
        labels: dict[int, str] = {}  # 云端 speaker_id → 角色X，出场顺序全局累计
        with tempfile.TemporaryDirectory(prefix="asr-cloud-") as tmp:
            work = Path(tmp)
            for clip, clip_path in pause_split.split_wav(wav_path, chunks, work):
                for sentence in self._call(MultiModalConversation, clip_path, sample_rate):
                    segments.append(self._segment(clip.start, sentence, labels))
        segments.sort(key=lambda s: s.start)
        return segments

    def _chunks(self, wav_path: Path) -> list[pause_split.Clip]:
        """能量停顿切 ≤_CHUNK_S 片；分析失败退整条，超限片硬等分兜底。"""
        import wave

        try:
            clips = pause_split.speech_clips(wav_path, max_clip_s=self._CHUNK_S)
        except (OSError, pause_split.PauseAnalysisUnavailable) as exc:
            with wave.open(str(wav_path), "rb") as wf:
                duration = wf.getnframes() / wf.getframerate()
            _LOGGER.warning(
                "停顿切分退回整条后按 %ss 硬等分（%s: %s）：切点不再落在真实停顿上",
                self._CHUNK_S,
                type(exc).__name__,
                exc,
            )
            clips = [pause_split.Clip(0.0, duration)]
        chunks: list[pause_split.Clip] = []
        for clip in clips:
            span = clip.end - clip.start
            if span <= self._CHUNK_S:
                chunks.append(clip)
                continue
            parts = int(span / self._CHUNK_S) + (1 if span % self._CHUNK_S else 0)
            step = span / parts
            for k in range(parts):
                chunks.append(
                    pause_split.Clip(clip.start + k * step, clip.start + (k + 1) * step)
                )
        return chunks

    _NET_BACKOFF = (5.0, 15.0)  # SDK 网络类异常短退避：抖动型故障两轮内多数自愈

    def _call(
        self, client: Any, clip_path: Path, sample_rate: int
    ) -> list[dict[str, Any]]:
        """单片同步转写，返回 sentences 列表（字级 words 含 speaker_id）。

        SDK 网络类异常短退避重试（一次抖动不该让整片切片连坐跳过）；业务
        响应（status_code != 200：配额/参数/模型错）不重试如实上抛。
        """
        import time  # noqa: PLC0415

        kwargs: dict[str, Any] = {}
        if self._diarization:
            kwargs["speaker_diarization_enabled"] = True
        rsp = None
        last_exc: Exception | None = None
        for attempt in range(len(self._NET_BACKOFF) + 1):
            try:
                rsp = client.call(
                    model=self._model,
                    messages=[{"role": "user", "content": [{"audio": f"file://{clip_path}"}]}],
                    format="wav",
                    sample_rate=str(sample_rate),
                    api_key=self._api_key,  # 逐请求带：SDK 的模块级 api_key 会被并发任务互覆
                    **kwargs,
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - SDK 网络层异常类型不承诺，宽捕
                last_exc = exc
                if attempt >= len(self._NET_BACKOFF):
                    break
                pause = self._NET_BACKOFF[attempt]
                _LOGGER.warning(
                    "云端转写网络类失败（%s），%.0fs 后重试 (%d/%d)",
                    exc, pause, attempt + 1, len(self._NET_BACKOFF),
                )
                time.sleep(pause)
        if last_exc is not None:
            raise RuntimeError(
                f"云端转写失败（{self._model}，已重试 {len(self._NET_BACKOFF)} 次）: {last_exc}"
            ) from last_exc
        assert rsp is not None
        if rsp.status_code != 200:
            raise RuntimeError(
                f"云端转写失败（{self._model}）: {rsp.code} {rsp.message}"
            )
        out = rsp.output
        sents = out.get("sentences")
        if not sents:
            inner = out.get("output")
            sents = inner.get("sentences") if isinstance(inner, dict) else None
        return list(sents or [])

    def _segment(
        self, offset_s: float, sentence: dict[str, Any], labels: dict[int, str]
    ) -> AsrSegment:
        """单句 → AsrSegment：片内毫秒时间戳 + 片起点偏移锚定到整集时间轴。"""
        start = int(sentence.get("begin_time", 0)) / 1000.0 + offset_s
        end = int(sentence.get("end_time", 0)) / 1000.0 + offset_s
        words: list[WordSpan] = []
        speaker_raw: int | None = None
        for w in sentence.get("words", []):
            text = str(w.get("text", "")).strip()
            if text == "":
                continue  # 词间空隙占位（" "）不带语义
            raw = w.get("speaker_id")
            if speaker_raw is None and raw is not None:
                speaker_raw = int(raw)
            words.append(
                WordSpan(
                    start=round(int(w.get("begin_time", 0)) / 1000.0 + offset_s, 3),
                    end=round(int(w.get("end_time", 0)) / 1000.0 + offset_s, 3),
                    word=text,
                )
            )
        text = str(sentence.get("text", "")).strip()
        if not words and text:
            # 无字级明细的模型（fun-asr 系）：整句一个词，时间不丢
            words = [WordSpan(start=round(start, 3), end=round(end, 3), word=text)]
        speaker: str | None = None
        if speaker_raw is not None:
            if speaker_raw not in labels:
                labels[speaker_raw] = _speaker_label(len(labels))
            speaker = labels[speaker_raw]
        return AsrSegment(
            start=round(start, 3),
            end=round(end, 3),
            text=text,
            speaker=speaker,
            words=words,
        )
