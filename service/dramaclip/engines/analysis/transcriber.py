"""ASR 引擎族：faster-whisper（默认，已实测）/ SenseVoice（funasr）/ Paraformer（funasr）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from dramaclip.engines.analysis.models import AsrSegment, WordSpan

_LOGGER = logging.getLogger(__name__)
_CUDA_PROBLEM = re.compile(r"cublas|cudnn|cudart|cuda|gpu|int8 compute type", re.I)


def simplify(text: str) -> str:
    """繁→简归一（opencc，ml extras 懒加载；whisper 中文输出混繁体是已知行为）。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    return str(OpenCC("t2s").convert(text))

if TYPE_CHECKING:
    # 仅类型检查期导入（运行时懒加载；缺依赖时经 ignore_missing_imports 兜底）
    from faster_whisper import WhisperModel
    from funasr import AutoModel


class AsrEngine(Protocol):
    """ASR 引擎接口：输入 16k 单声道 wav，输出带时间戳的转写段。"""

    @property
    def name(self) -> str: ...

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]: ...


class FasterWhisperEngine:
    """faster-whisper（CTranslate2，CPU 可用，模型自动下载到 models_dir）。"""

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        models_dir: Path | None = None,
        compute_type: str = "auto",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._models_dir = models_dir
        self._compute_type = compute_type
        self._model: WhisperModel | None = None

    @property
    def name(self) -> str:
        return f"faster_whisper:{self._model_size}"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        try:
            return self._run(self._ensure_model(), wav_path, language, hotwords)
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            # cuBLAS/cuDNN 缺失往往在首次推理（惰性计算）时才暴露，构造期兜不住
            if self._device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            _LOGGER.warning("CUDA 推理失败，自动回退 CPU：%s", exc)
            from faster_whisper import WhisperModel  # ml extras 懒加载

            cpu_model = self._create(WhisperModel, "cpu")
            self._model = cpu_model  # 缓存 CPU 模型，后续集不再重复走失败的 CUDA 路径
            return self._run(cpu_model, wav_path, language, hotwords)

    def _run(
        self, model: WhisperModel, wav_path: Path, language: str, hotwords: str
    ) -> list[AsrSegment]:
        # word_timestamps：字级时间戳+概率，供 OCR 融合对齐（关闭则 words 为空）
        segments, _info = model.transcribe(
            str(wav_path),
            language=language,
            vad_filter=True,
            word_timestamps=True,
            hotwords=hotwords or None,
        )
        result: list[AsrSegment] = []
        for seg in segments:
            text = simplify(seg.text.strip())
            if not text:
                continue
            words = [
                WordSpan(
                    start=word.start,
                    end=word.end,
                    word=simplify(word.word.strip()),
                    probability=word.probability,
                )
                for word in (seg.words or [])
                if word.word.strip()
            ]
            result.append(AsrSegment(start=seg.start, end=seg.end, text=text, words=words))
        return result

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel  # ml extras 懒加载

            self._model = self._create(WhisperModel, self._device)
        return self._model

    def _create(self, cls: type[WhisperModel], device: str) -> WhisperModel:
        try:
            return cls(
                self._model_size,
                device=device,
                compute_type=self._compute_for(device),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            if device != "cpu" and _CUDA_PROBLEM.search(str(exc)):
                # GPU 不可用（缺 cuBLAS/cuDNN、驱动不兼容等）：诚实降级 CPU 并留痕
                _LOGGER.warning("CUDA 初始化失败，自动回退 CPU：%s", exc)
                return cls(
                    self._model_size,
                    device="cpu",
                    compute_type=self._compute_for("cpu"),
                    download_root=str(self._models_dir) if self._models_dir else None,
                )
            raise

    def _compute_for(self, device: str) -> str:
        """int8 是 CPU 档：ctranslate2 的 CUDA 后端在没有高效 int8 GEMM 的卡上直接拒绝，
        硬塞的后果只是触发回退——GPU 在场却永远用不上。

        这层映射兜的是存量：老设置库里落盘的 int8、或调用方显式传入的 int8——设备不是
        cpu 时改交 auto，由库按实际解析到的设备挑最快可用档（CUDA→float16/float32，
        CPU→int8）。其余显式档位原样透传——业主自己选的，尊重。
        """
        if device != "cpu" and self._compute_type == "int8":
            return "auto"
        return self._compute_type


class SenseVoiceEngine:
    """SenseVoice（funasr，含 VAD 与情绪标签）。依赖较重（torch），按需安装。"""

    def __init__(self, model_dir: Path | None = None, *, models_dir: Path | None = None) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "iic" / "SenseVoiceSmall" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._model: AutoModel | None = None

    @property
    def name(self) -> str:
        return "sensevoice"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        model = self._ensure_model()
        raw = model.generate(
            input=str(wav_path),
            cache={},
            language=language,
            output_timestamp=True,
        )
        return _parse_sensevoice(raw)

    def _ensure_model(self) -> AutoModel:
        if self._model is None:
            from funasr import AutoModel  # ml extras 懒加载

            if self._model_dir is not None and self._model_dir.is_dir():
                self._model = AutoModel(model=str(self._model_dir))
            else:
                self._model = AutoModel(model="iic/SenseVoiceSmall")
        return self._model


def _parse_sensevoice(raw: list) -> list[AsrSegment]:  # type: ignore[type-arg]
    """funasr 输出 [{text, timestamp:[[beg_ms,end_ms], ...]}]（时间戳按字/词分组）。"""
    segments: list[AsrSegment] = []
    for item in raw:
        timestamps = item.get("timestamp") or []
        text_chunks = str(item.get("text", "")).split()
        if not timestamps:
            continue
        for cursor, span in enumerate(timestamps):
            beg_ms, end_ms = span
            chunk = text_chunks[cursor] if cursor < len(text_chunks) else ""
            if chunk:
                segments.append(AsrSegment(start=beg_ms / 1000, end=end_ms / 1000, text=chunk))
    # 合并为句级（简单拼接为整段，句级切分由 W3 语义层细化）
    if segments:
        merged = AsrSegment(
            start=segments[0].start,
            end=segments[-1].end,
            text="".join(seg.text for seg in segments),
        )
        return [merged]
    return []


class ParaformerEngine:
    """Paraformer-large（funasr 同栈）：字级时间戳原生，热词有原生槽位。

    与 SenseVoice 的两处关键差异：长音频靠 `batch_size_s` 动态批整集进；
    时间戳是字级的——按字间静音间隙聚成句级段，供 OCR 融合与台词保护区用。

    说话人分离（`spk_model_dir` 在场时启用）：funasr 的 diarization 路径
    **必须**挂 vad_model（嵌入按语音区间提取，无 vad 直接没有输入窗），
    且 spk_mode 显式走 "vad_segment"——"punc_segment"（默认值）需要标点模型，
    不装标点时会先打一条 error 日志再被库自己改回，明着写对省那条假警报。
    说话人数：`num_speakers>0` 经 `preset_spk_num` 指定，0 交给聚类自动估
    （1~15 人范围，短剧每集 2~6 人绰绰有余）。
    """

    # 字间隙超过这个数（秒）就断句：短剧台词句间停顿普遍 >0.5s，标点模型不挂
    # （那是另两笔下载），靠间隙本身就是可靠的句边界。
    _SENTENCE_GAP_S = 0.6

    # CAM++ 权重的仓库实名（registry 同名判据；funasr 本地加载默认找 model.pt）
    _CAMPP_WEIGHT = "campplus_cn_common.bin"

    def __init__(
        self,
        model_dir: Path | None = None,
        *,
        models_dir: Path | None = None,
        vad_model_dir: Path | None = None,
        spk_model_dir: Path | None = None,
        num_speakers: int = 0,
    ) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "paraformer" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._vad_model_dir = vad_model_dir
        self._spk_model_dir = spk_model_dir
        self._num_speakers = num_speakers
        self._model: AutoModel | None = None

    @property
    def name(self) -> str:
        return "paraformer"

    @property
    def diarization(self) -> bool:
        """说话人分离是否启用（由调用方决定传入 spk 模型目录与否）。"""
        return self._spk_model_dir is not None

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        model = self._ensure_model()
        with _punc_false_alarm_silenced():
            raw = model.generate(
                input=str(wav_path),
                batch_size_s=300,  # 长音频动态批：整集 wav 一次进，按 300s 预算切批
                hotword=hotwords or None,  # paraformer 原生热词槽（热词反哺直接受益）
                # 必须显式要时间戳：不传时 funasr 只回 {key,text}，_parse_paraformer
                # 对无时间戳条目整条丢弃 → 全文静默变空（2026-09-24 真样例实测）。
                output_timestamp=True,
                **(
                    {"preset_spk_num": self._num_speakers}
                    if self.diarization and self._num_speakers > 0
                    else {}
                ),
            )
        segments = _parse_paraformer(raw, self._SENTENCE_GAP_S)
        spans = _spk_spans(raw)
        return _assign_speakers(segments, spans) if spans else segments

    def _ensure_model(self) -> AutoModel:
        if self._model is None:
            from funasr import AutoModel  # ml extras 懒加载

            spk_kwargs: dict[str, Any] = {}
            if self.diarization:
                spk_dir = self._spk_model_dir
                vad_dir = self._vad_model_dir
                assert spk_dir is not None  # diarization=True 的定义就是这个字段在场
                spk_kwargs["vad_model"] = (
                    str(vad_dir) if vad_dir is not None and vad_dir.is_dir() else "fsmn-vad"
                )
                if spk_dir.is_dir():
                    spk_kwargs["spk_model"] = str(spk_dir)
                    # funasr 本地目录加载把权重名硬编码成 model.pt（download_from_hub
                    # 的断言），CAM++ 的权重实名是 campplus_cn_common.bin——经
                    # spk_kwargs 组件通道用 init_param 指路（绝对路径绕开 CWD 相对
                    # 解析）。不能放顶层 kwargs：那里会把 cam++ 权重喂给主模型。
                    weight = spk_dir / self._CAMPP_WEIGHT
                    if weight.is_file():
                        spk_kwargs["spk_kwargs"] = {"init_param": str(weight)}
                else:
                    spk_kwargs["spk_model"] = "cam++"
                spk_kwargs["spk_mode"] = "vad_segment"
            if self._model_dir is not None and self._model_dir.is_dir():
                self._model = AutoModel(
                    model=str(self._model_dir), disable_update=True, **spk_kwargs
                )
            else:
                self._model = AutoModel(
                    model="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
                    disable_update=True,  # 启动期联网检查版本：桌面应用不联网也能转写
                    **spk_kwargs,
                )
        return self._model


def _parse_paraformer(raw: list, gap_s: float) -> list[AsrSegment]:  # type: ignore[type-arg]
    """[{text, timestamp:[[beg_ms,end_ms], ...]}] → 句级段（按字间隙聚句 + 字级 words）。

    text 与 timestamp 逐字配对；长度对不上时按可配对的前缀走、剩余文本并入末字
    的跨度——文本一个不丢，边界取实测值（量不到的不编）。
    """
    segments: list[AsrSegment] = []
    for item in raw:
        text = str(item.get("text", "")).strip()
        timestamps = [span for span in (item.get("timestamp") or []) if len(span) == 2]
        if not text or not timestamps:
            continue
        chars = [ch for ch in text if not ch.isspace()]
        words = [
            WordSpan(start=beg_ms / 1000, end=end_ms / 1000, word=char)
            for char, (beg_ms, end_ms) in _pair(chars, timestamps)
        ]
        for run in _group_by_gap(words, gap_s):
            segments.append(
                AsrSegment(
                    start=run[0].start,
                    end=run[-1].end,
                    text=simplify("".join(w.word for w in run)),
                    words=list(run),
                )
            )
    return segments


_PUNC_FALSE_ALARM = "Missing punc_model, which is required by spk_model."


class _ExactMessageFilter(logging.Filter):
    """只放行不含指定原文的日志记录——精确到整句，不误伤同通道其他消息。"""

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def filter(self, record: logging.LogRecord) -> bool:
        return self._message not in record.getMessage()


@contextlib.contextmanager
def _punc_false_alarm_silenced() -> Iterator[None]:
    """vad_segment 模式下静音 funasr 的「缺标点模型」ERROR。

    库在 spk 路径上无差别检查 punc（`auto_model.py`：`elif raw_text is None` 分支
    对 vad_segment 模式也报 ERROR），但 vad_segment 只靠 VAD 区间拼句，本就不需要
    标点模型——这是我们主动选的配置，不是缺件。过滤器挂在 root（funasr 用模块级
    logging.error 直打 root），只在 generate 期间在场、消息精确匹配，别的 ERROR
    一条不放行。
    """
    filt = _ExactMessageFilter(_PUNC_FALSE_ALARM)
    root = logging.getLogger()
    root.addFilter(filt)
    try:
        yield
    finally:
        root.removeFilter(filt)


def _spk_spans(raw: list) -> list[tuple[float, float, int]]:  # type: ignore[type-arg]
    """从 funasr 输出收集说话人区间 [(start_s, end_s, 簇id)]（sentence_info，ms 单位）。

    没启用分离时 raw 里没有 sentence_info，返回空表——调用方据此跳过归属。
    """
    spans: list[tuple[float, float, int]] = []
    for item in raw:
        for sentence in item.get("sentence_info") or []:
            try:
                start = float(sentence["start"]) / 1000
                end = float(sentence["end"]) / 1000
                label = int(sentence["spk"])
            except (KeyError, TypeError, ValueError):
                continue  # 缺字段的条目跳过，不编造归属
            if end > start:
                spans.append((start, end, label))
    return spans


def _assign_speakers(
    segments: list[AsrSegment], spans: list[tuple[float, float, int]]
) -> list[AsrSegment]:
    """句级段按重叠时长多数归属说话人：一段话里的字属谁，看谁的声音盖的时间长。

    与任何区间都不重叠的段（纯静音误检等）speaker 保持 None——量不到的不编。
    """
    out: list[AsrSegment] = []
    for seg in segments:
        totals: dict[int, float] = {}
        for start, end, label in spans:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > 0:
                totals[label] = totals.get(label, 0.0) + overlap
        if not totals:
            out.append(seg)
            continue
        winner = max(totals, key=lambda label: totals[label])
        out.append(
            AsrSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=_speaker_label(winner),
                emotion=seg.emotion,
                words=seg.words,
                source=seg.source,
            )
        )
    return out


def _speaker_label(label: int) -> str:
    """簇 id → 界面可读标签：角色A/角色B…（id 是聚类产物，不代表真实姓名）。"""
    if 0 <= label < 26:
        return f"角色{chr(ord('A') + label)}"
    return f"角色{label + 1}"


def _pair(
    chars: list[str], timestamps: list[list[float]]
) -> list[tuple[str, tuple[float, float]]]:
    """文本字与时间戳逐位配对；时间戳短时，剩余文本并入末个时间戳的跨度。"""
    if len(chars) <= len(timestamps):
        return [(char, (span[0], span[1])) for char, span in zip(chars, timestamps, strict=False)]
    if not timestamps:
        return []
    head = [(char, (span[0], span[1])) for char, span in zip(chars, timestamps, strict=False)]
    tail = "".join(chars[len(timestamps) - 1 :])
    last = timestamps[-1]
    return [*head[: len(timestamps) - 1], (tail, (last[0], last[1]))]


def _group_by_gap(
    words: list[WordSpan], gap_s: float
) -> list[list[WordSpan]]:
    """相邻字跨度间隙超阈值的切开；同一句内的字归一段。"""
    runs: list[list[WordSpan]] = []
    for word in words:
        if runs and word.start - runs[-1][-1].end <= gap_s:
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


class DashscopeParaformerEngine:
    """百炼 Paraformer（云端，DashScope 文件转写）：无本地模型，按量计费。

    与本地 paraformer 的同源模型，云端推理——弱机/无 GPU 用户的 ASR 跃升路径
    （P1 云端化）。文件转写是异步任务：提交 → 轮询 → 拉转写 JSON。
    句级时间戳 + 字级 words 全有，AsrSegment 同构，OCR 融合照常工作。
    说话人分离云端不返回（speaker=None）；诊断与融合不依赖它也能工作。
    """

    _POLL_INTERVAL_S = 3.0
    _POLL_TIMEOUT_S = 600.0

    def __init__(self, api_key: str, model: str = "paraformer-v2") -> None:
        key = api_key.strip()
        if key == "":
            raise ValueError(
                "百炼 Paraformer（云端）需要 API Key：请在引擎中心填写 asr.api_key"
            )
        self._api_key = key
        self._model = model

    @property
    def name(self) -> str:
        return f"dashscope_paraformer:{self._model}"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        import dashscope
        from dashscope.audio.asr import Transcription

        dashscope.api_key = self._api_key
        hints = ["zh"] if language.startswith("zh") else [language]
        # 内联热词云端不支持（需预建 vocabulary_id，P1 后续接）；参数如实不透传
        submit = Transcription.call(
            model=self._model,
            file_urls=[str(wav_path)],
            language_hints=hints,
        )
        if submit.status_code != 200:
            raise RuntimeError(f"转写任务提交失败: {submit.message}")
        task_id = submit.output["task_id"]
        deadline = time.monotonic() + self._POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            polled = Transcription.fetch(task=task_id)
            if polled.status_code != 200:
                raise RuntimeError(f"转写任务查询失败: {polled.message}")
            status = polled.output.get("task_status")
            if status in ("PENDING", "RUNNING"):
                time.sleep(self._POLL_INTERVAL_S)
                continue
            if status != "SUCCEEDED":
                raise RuntimeError(f"转写任务失败: {polled.output.get('message')}")
            return self._collect(polled.output.get("results") or [])
        raise RuntimeError(f"转写任务超时（{self._POLL_TIMEOUT_S:.0f}s）")

    def _collect(self, results: list[dict[str, Any]]) -> list[AsrSegment]:
        """各文件转写 JSON 的 sentences → AsrSegment（字级 words 原样带上）。"""
        import urllib.request

        segments: list[AsrSegment] = []
        for item in results:
            url = item.get("transcription_url")
            if not url:
                continue
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            for transcript in payload.get("transcripts", []):
                for sentence in transcript.get("sentences", []):
                    words = [
                        WordSpan(
                            start=int(w.get("begin_time", 0)) / 1000.0,
                            end=int(w.get("end_time", 0)) / 1000.0,
                            word=str(w.get("text", "")),
                        )
                        for w in sentence.get("words", [])
                    ]
                    segments.append(
                        AsrSegment(
                            start=int(sentence.get("begin_time", 0)) / 1000.0,
                            end=int(sentence.get("end_time", 0)) / 1000.0,
                            text=str(sentence.get("text", "")).strip(),
                            words=words,
                        )
                    )
        return segments
