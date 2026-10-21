"""ASR 引擎族：faster-whisper（默认，已实测）/ SenseVoice（funasr）/ Paraformer（funasr）。
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from dramaclip.engines.analysis import pause_split
from dramaclip.engines.analysis.models import AsrSegment, WordSpan
from dramaclip.infra import compute
from dramaclip.infra.model_manager import worker_bridge

_LOGGER = logging.getLogger(__name__)
_CUDA_PROBLEM = re.compile(r"cublas|cudnn|cudart|cuda|gpu|int8 compute type", re.I)


def _ct2_cuda_available() -> bool:
    """CT2 能否看到 CUDA 设备；探不到一律按不可用，构造期再用真实失败兜底。"""
    try:
        import ctranslate2

        return bool(ctranslate2.get_cuda_device_count() > 0)
    except Exception:  # noqa: BLE001 - 坏装/未装是常态，不是转写失败
        return False


def _report_from_state(
    component: str, requested: str, actual: str | None, fallback_reason: str
) -> compute.ComputeReport | None:
    """引擎状态 → 回执：没真加载过就返回 None；回退时 resolved 记曾尝试的 cuda。"""
    if actual is None:
        return None
    resolved = "cpu" if requested == "cpu" or actual == "cpu" else "cuda"
    if fallback_reason:
        resolved = "cuda"
    return compute.ComputeReport(
        component=component,
        requested=requested,
        resolved=resolved,
        actual=actual,
        fallback=bool(fallback_reason),
        reason=fallback_reason,
    )


def _probe_cuda_op(device: str) -> str:
    """真实小算子探针：返回空串=可算，否则失败原因。

    `torch.cuda.is_available()` 只说明编译/驱动可见，且 funasr 在不可见时会把
    device 静默改成 cpu——不先算一下，显式 cuda 就会被静默落 CPU。
    """
    try:
        import torch

        (torch.ones(4, device=device) * 2).sum().item()
    except Exception as exc:  # noqa: BLE001 - CPU-only torch/坏驱动都算不可算
        return f"{type(exc).__name__}: {exc}"
    return ""


def _model_device(model: Any) -> str | None:
    """模型真实落点：参数设备是物理证据，funasr 解析后的 kwargs.device 是退路。"""
    inner = getattr(model, "model", model)
    parameters = getattr(inner, "parameters", None)
    if callable(parameters):
        try:
            first = next(parameters())
        except (StopIteration, TypeError):
            first = None
        kind = getattr(getattr(first, "device", None), "type", None)
        if kind in {"cuda", "cpu"}:
            return str(kind)
    resolved = getattr(model, "kwargs", None)
    if isinstance(resolved, dict):
        value = str(resolved.get("device") or "")
        if value:
            return "cuda" if value.startswith("cuda") else "cpu"
    return None


def _adopt_loaded_device(
    component: str, requested: str, wanted: str, model: Any
) -> tuple[str, str]:
    """加载成功后的落点裁决：返回 (actual, fallback_reason)，违诺直接抛。"""
    actual = _model_device(model)
    if actual is None:
        # 读不到落点就不许替显式 cuda 打包票；auto 至少探针已经证明可算。
        if requested == "cuda":
            raise compute.ComputeUnavailableError(
                f"{component} 请求 CUDA，但无法确认模型的实际落点"
            )
        actual = "cuda" if wanted.startswith("cuda") else "cpu"
    if requested == "cpu" and actual != "cpu":
        raise compute.ComputeUnavailableError(
            f"{component} 请求 CPU，funasr 把模型落在 {actual}"
        )
    if wanted.startswith("cuda") and actual != "cuda":
        if requested == "cuda":
            raise compute.ComputeUnavailableError(
                f"{component} 请求 CUDA，funasr 把模型落在 {actual}（静默回退）"
            )
        return "cpu", f"funasr 把模型落在 {actual}"
    return actual, ""


def _resolve_torch_device(device: str) -> str:
    """asr.device 设置值 → funasr AutoModel 的 device 实参（进程内路径专用）。

    auto = 交给 torch 探测（有可用 CUDA 即 cuda:0）；显式 cuda 同样解析成
    cuda:0；解析结果仍可能初始化失败（驱动/显存），由引擎的加载回退兜底。
    """
    if device in ("", "auto"):
        try:
            import torch

            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - torch 缺失/坏装一律 CPU（funasr 基线路径）
            return "cpu"
    if device == "cuda":
        return "cuda:0"
    return device


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


# ---- funasr 双路径装配（E-2）：进程内优先（dev/测试），冻结态走 tts-venv worker ----
# 打包态主包不含 torch/funasr（build-service excludes），此时 funasr 从本地智能
# 运行环境（tts-venv）的 worker 进程获得；dev 装了 ml 组或测试桩在 sys.modules
# 里放了 funasr 时走进程内真 import——两个分支对引擎只暴露同一个 .generate() 形状。


class _FunasrWorker:
    """venv 内 funasr AutoModel 的进程代理：``.generate(**kwargs)`` 与真模型同形。

    生命周期跟引擎实例（AnalysisRuntime 缓存单例 → 全应用一个 worker），进程
    统一在 service_app 退出时由桥的 shutdown 回收——不收会在 Windows 上留占着
    模型内存的孤儿进程（indextts2 同款教训）。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        from dramaclip.engines.tts.workers import funasr_worker

        self._inner = worker_bridge.VenvWorker(Path(funasr_worker.__file__), config)
        self.device = "cpu"
        self.ready: dict[str, Any] = {}

    def start(self) -> None:
        ready = self._inner.start()
        self.ready = dict(ready)
        self.device = str(ready.get("device") or "cpu")

    def generate(self, **kwargs: Any) -> list:  # type: ignore[type-arg]
        payload = {**kwargs, "input": str(kwargs.get("input", ""))}
        msg = self._inner.request({"kwargs": payload})
        if not msg.get("ok"):
            raise RuntimeError(f"funasr 转写失败: {msg.get('error')}")
        return list(msg.get("raw") or [])

    @property
    def _proc(self) -> Any:
        return self._inner.proc  # 测试断言用：shutdown 后为 None


def shutdown_funasr_workers() -> None:
    """service_app 退出钩子（薄别名）：回收 funasr/kokoro 等全部 venv worker。"""
    worker_bridge.shutdown_venv_workers()


def _spawn_funasr_worker(config: dict[str, Any]) -> _FunasrWorker:
    worker = _FunasrWorker(config)
    worker_bridge.register_venv_worker(worker._inner)
    worker.start()
    return worker


def _inproc_funasr() -> Any:
    """进程内 funasr.AutoModel；不可用返回 None（调用方走 venv worker 并给引导文案）。"""
    try:
        from funasr import AutoModel  # ml extras 懒加载/测试桩
    except ImportError:
        return None
    return AutoModel


class AsrEngine(Protocol):
    """ASR 引擎接口：输入 16k 单声道 wav，输出带时间戳的转写段。"""

    @property
    def name(self) -> str: ...

    @property
    def supports_diarization(self) -> bool:
        """能否给转写段打说话人标签——`asr.diarization` 的认领方，做不到必须如实说。"""
        ...

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]: ...

    def compute(self) -> compute.ComputeReport | None:
        """最近一次真实转写的算力回执；没跑过返回 None，不猜。"""
        ...


class FasterWhisperEngine:
    """faster-whisper（CTranslate2，CPU 可用，模型自动下载到 models_dir）。"""

    supports_diarization = False  # 该引擎无说话人通道

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        models_dir: Path | None = None,
        compute_type: str = "auto",
    ) -> None:
        self._model_size = model_size
        self._requested = compute.normalize_requested(device)
        self._models_dir = models_dir
        self._compute_type = compute_type
        self._model: WhisperModel | None = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

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
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，推理失败：{type(exc).__name__}: {exc}"
                ) from exc
            if self._actual_device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            _LOGGER.warning("CUDA 推理失败，自动回退 CPU：%s", exc)
            from faster_whisper import WhisperModel  # ml extras 懒加载

            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            self._model = self._create(WhisperModel, "cpu")
            return self._run(self._model, wav_path, language, hotwords)

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

            if self._requested == "cpu":
                target = "cpu"
            else:
                target = "cuda" if self._requested == "cuda" or _ct2_cuda_available() else "cpu"
            self._model = self._create(WhisperModel, target)
        return self._model

    def _create(self, cls: type[WhisperModel], device: str) -> WhisperModel:
        try:
            model = cls(
                self._model_size,
                device=device,
                compute_type=self._compute_for(device),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，初始化失败：{type(exc).__name__}: {exc}"
                ) from exc
            _LOGGER.warning("CUDA 初始化失败，自动回退 CPU：%s", exc)
            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            model = cls(
                self._model_size,
                device="cpu",
                compute_type=self._compute_for("cpu"),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        else:
            self._actual_device = "cuda" if device != "cpu" else "cpu"
        return model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.whisper", self._requested, self._actual_device, self._fallback_reason
        )

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

    supports_diarization = False  # 情绪有通道，说话人没有：接了分离模型再改声明

    def __init__(
        self, model_dir: Path | None = None, *, models_dir: Path | None = None,
        device: str = "auto",
    ) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "iic" / "SenseVoiceSmall" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._requested = compute.normalize_requested(device)
        self._model: Any = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

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

    def _ensure_model(self) -> Any:
        if self._model is None:
            auto_model = _inproc_funasr()
            if auto_model is None:
                self._model = self._venv_model()
                return self._model
            device = _resolve_torch_device(self._requested)
            if device.startswith("cuda"):
                problem = _probe_cuda_op(device)
                if problem:
                    if self._requested == "cuda":
                        raise compute.ComputeUnavailableError(
                            f"SenseVoice 请求 CUDA，但 CUDA 不可计算：{problem}"
                        )
                    _LOGGER.warning("SenseVoice CUDA 探针失败回退 CPU：%s", problem)
                    self._actual_device = "cpu"
                    self._fallback_reason = problem
                    device = "cpu"
            kwargs: dict[str, Any] = {"model": str(self._model_dir) if (
                self._model_dir is not None and self._model_dir.is_dir()
            ) else "iic/SenseVoiceSmall", "device": device}
            try:
                self._model = auto_model(**kwargs)
            except Exception as exc:  # noqa: BLE001 - CUDA 类失败按请求语义处理
                if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                    raise
                if self._requested == "cuda":
                    raise compute.ComputeUnavailableError(
                        f"SenseVoice 请求 CUDA，加载失败：{type(exc).__name__}: {exc}"
                    ) from exc
                _LOGGER.warning("SenseVoice CUDA 加载失败回退 CPU：%s", str(exc)[:160])
                self._actual_device = "cpu"
                self._fallback_reason = f"{type(exc).__name__}: {exc}"
                kwargs["device"] = "cpu"
                self._model = auto_model(**kwargs)
            else:
                self._actual_device, reason = _adopt_loaded_device(
                    "SenseVoice", self._requested, device, self._model
                )
                if reason:
                    self._fallback_reason = reason
        return self._model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.funasr", self._requested, self._actual_device, self._fallback_reason
        )

    def _venv_model(self) -> _FunasrWorker:
        """冻结/无 ml 态：本地智能运行环境里的 funasr worker（构造语义 worker 端镜像）。"""
        model_id = (
            str(self._model_dir)
            if self._model_dir is not None and self._model_dir.is_dir()
            else "iic/SenseVoiceSmall"
        )
        worker = _spawn_funasr_worker({
            "engine": "sensevoice",
            "model": model_id,
            "device": self._requested,
        })
        self._adopt_worker_hello(worker)
        _LOGGER.info("SenseVoice 走本地运行环境 worker（device=%s）", worker.device)
        return worker

    def _adopt_worker_hello(self, worker: _FunasrWorker) -> None:
        """worker 就绪行是运行态唯一证据：父进程曾把 device 读出来又丢了。"""
        hello = worker.ready
        self._actual_device = "cuda" if worker.device.startswith("cuda") else "cpu"
        self._fallback_reason = (
            str(hello.get("reason") or "") if hello.get("fallback") else ""
        )


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

    supports_diarization = True  # CAM++ 聚类通道已接线（见类 docstring）
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
        device: str = "auto",
    ) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "paraformer" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._vad_model_dir = vad_model_dir
        self._spk_model_dir = spk_model_dir
        self._num_speakers = num_speakers
        self._requested = compute.normalize_requested(device)
        self._model: Any = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

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
        try:
            clips = pause_split.speech_clips(wav_path)
        except (OSError, pause_split.PauseAnalysisUnavailable) as exc:
            # 停顿分析量不出来（文件不可读/过短）→ 退回整条直喂（分档：老路径仍可用）。
            # 只认这一类型：编程错误往这儿抛就是真失败，让它出去。
            _LOGGER.warning(
                "停顿切分退回整条直喂（%s: %s）：字级时间戳失去片段起点锚，跨停顿并句可能复现",
                type(exc).__name__,
                exc,
            )
            clips = []
        with _punc_false_alarm_silenced():
            if len(clips) <= 1:
                return self._transcribe_one(model, wav_path, language, hotwords)
            # 停顿切分：BGM 素材下 funasr 内部 VAD 分不清「人声停了」与「安静」，
            # 跨停顿并句 + 字戳插值漂移都源于整条直喂。按能量谷切短语片段逐段转写，
            # 时间戳以片段起点为锚（真实切分位置），并句/串音物理消失。
            work = wav_path.parent / f"{wav_path.stem}-clips"
            segments: list[AsrSegment] = []
            try:
                for clip, clip_path in pause_split.split_wav(wav_path, clips, work):
                    for seg in self._transcribe_one(model, clip_path, language, hotwords):
                        # 词级时间戳同样是 clip 相对值：只平移 start/end 会把词锚留在
                        # 片段内——refine 字流按词取时间，整份时间轴就会坍缩到首个
                        # clip 的跨度（真机第1集实锤：46 段全挤 0-11.58s）。
                        shifted_words = [
                            w.model_copy(
                                update={
                                    "start": round(w.start + clip.start, 3),
                                    "end": round(w.end + clip.start, 3),
                                }
                            )
                            for w in (seg.words or [])
                        ]
                        segments.append(
                            seg.model_copy(
                                update={
                                    "start": round(seg.start + clip.start, 3),
                                    "end": round(seg.end + clip.start, 3),
                                    "words": shifted_words,
                                }
                            )
                        )
            finally:
                shutil.rmtree(work, ignore_errors=True)
            segments.sort(key=lambda s: s.start)
            return segments

    def _transcribe_one(
        self, model: Any, wav_path: Path, language: str, hotwords: str
    ) -> list[AsrSegment]:
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

    def _ensure_model(self) -> Any:
        if self._model is None:
            auto_model = _inproc_funasr()
            if auto_model is None:
                self._model = self._venv_model()
                return self._model
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
            device = _resolve_torch_device(self._requested)
            if device.startswith("cuda"):
                problem = _probe_cuda_op(device)
                if problem:
                    if self._requested == "cuda":
                        raise compute.ComputeUnavailableError(
                            f"Paraformer 请求 CUDA，但 CUDA 不可计算：{problem}"
                        )
                    _LOGGER.warning("Paraformer CUDA 探针失败回退 CPU：%s", problem)
                    self._actual_device = "cpu"
                    self._fallback_reason = problem
                    device = "cpu"
            model_id = str(self._model_dir) if (
                self._model_dir is not None and self._model_dir.is_dir()
            ) else "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
            kwargs: dict[str, Any] = {
                "model": model_id,
                "disable_update": True,  # 启动期联网检查版本：桌面应用不联网也能转写
                "device": device,
                **spk_kwargs,
            }
            try:
                self._model = auto_model(**kwargs)
            except Exception as exc:  # noqa: BLE001 - CUDA 类失败按请求语义处理
                if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                    raise
                if self._requested == "cuda":
                    raise compute.ComputeUnavailableError(
                        f"Paraformer 请求 CUDA，加载失败：{type(exc).__name__}: {exc}"
                    ) from exc
                _LOGGER.warning("Paraformer CUDA 加载失败回退 CPU：%s", str(exc)[:160])
                self._actual_device = "cpu"
                self._fallback_reason = f"{type(exc).__name__}: {exc}"
                kwargs["device"] = "cpu"
                self._model = auto_model(**kwargs)
            else:
                self._actual_device, reason = _adopt_loaded_device(
                    "Paraformer", self._requested, device, self._model
                )
                if reason:
                    self._fallback_reason = reason
        return self._model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.funasr", self._requested, self._actual_device, self._fallback_reason
        )

    def _venv_model(self) -> _FunasrWorker:
        """冻结/无 ml 态：本地智能运行环境里的 funasr worker（构造语义 worker 端镜像）。"""
        model_id = str(self._model_dir) if (
            self._model_dir is not None and self._model_dir.is_dir()
        ) else "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        worker = _spawn_funasr_worker({
            "engine": "paraformer",
            "model": model_id,
            "device": self._requested,
            "vad_model_dir": str(self._vad_model_dir) if self._vad_model_dir else None,
            "spk_model_dir": str(self._spk_model_dir) if self._spk_model_dir else None,
        })
        self._adopt_worker_hello(worker)
        _LOGGER.info(
            "Paraformer 走本地运行环境 worker（device=%s diarization=%s）",
            worker.device, self.diarization,
        )
        return worker

    def _adopt_worker_hello(self, worker: _FunasrWorker) -> None:
        hello = worker.ready
        self._actual_device = "cuda" if worker.device.startswith("cuda") else "cpu"
        self._fallback_reason = (
            str(hello.get("reason") or "") if hello.get("fallback") else ""
        )


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

    def _call(
        self, client: Any, clip_path: Path, sample_rate: int
    ) -> list[dict[str, Any]]:
        """单片同步转写，返回 sentences 列表（字级 words 含 speaker_id）。"""
        kwargs: dict[str, Any] = {}
        if self._diarization:
            kwargs["speaker_diarization_enabled"] = True
        rsp = client.call(
            model=self._model,
            messages=[{"role": "user", "content": [{"audio": f"file://{clip_path}"}]}],
            format="wav",
            sample_rate=str(sample_rate),
            api_key=self._api_key,  # 逐请求带：SDK 的模块级 api_key 会被并发任务互覆
            **kwargs,
        )
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
