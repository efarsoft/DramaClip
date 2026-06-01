"""
ASR 语音识别服务 - 支持多种引擎

引擎选项:
    - whisperx:       WhisperX (faster-whisper + wav2vec2 forced alignment)
    - faster-whisper: 基于 OpenAI Whisper 的优化版本
    - sensevoice:     阿里达摩院 SenseVoice，针对中文优化

自动选择优先级: WhisperX > faster-whisper > SenseVoice
WhisperX 提供 wav2vec2 强制对齐，词级时间戳精度从 ±100-300ms 提升到 ±10-30ms。

通过 config.toml 配置:
    [asr]
    engine = "auto"              # auto | whisperx | faster_whisper | sensevoice
    model = "base"               # faster-whisper: tiny/base/small/medium/large-v3/distil-large-v3
                                  # sensevoice: SenseVoice-small/SenseVoice-large
"""

import os
import threading
from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Callable, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger

# ASR 服务声明的中央 catalog 模型需求（required_model_repo 风格）
ASR_REQUIRED_MODELS = [
    "Systran/faster-whisper-large-v3",
    "iic/SenseVoiceSmall",
]


@dataclass
class ASRSegment:
    """ASR 识别片段"""
    id: str
    text: str
    start: float
    end: float
    speaker: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
        }


@dataclass
class ASRResult:
    """ASR 识别结果"""
    segments: List[ASRSegment] = field(default_factory=list)
    language: str = "zh"
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "language": self.language,
            "duration": self.duration,
        }


# ---------------------------------------------------------------------------
# Model manager – thread-local storage for thread safety
# 每个线程拥有独立的模型实例，避免并行执行时的线程安全问题
# ---------------------------------------------------------------------------

_thread_local = threading.local()
_model_lock = threading.Lock()
_model_device = "cpu"
_model_compute = "int8"


def _get_model(model_size: str = "base", device: Optional[str] = None,
               compute_type: Optional[str] = None) -> Any:
    """获取或创建 WhisperModel（线程本地存储版本）
    
    每个线程拥有独立的模型实例，支持并行执行多个ASR任务。
    """
    # 检查当前线程是否已有模型实例
    if hasattr(_thread_local, 'model_instance') and _thread_local.model_instance is not None:
        return _thread_local.model_instance

    # 模型加载需要加锁（避免同时加载多个相同模型）
    with _model_lock:
        # 双重检查
        if hasattr(_thread_local, 'model_instance') and _thread_local.model_instance is not None:
            return _thread_local.model_instance

        from faster_whisper import WhisperModel

        # ---------- 本地模型解析 & 自动下载 ----------
        from app.services.model_manager import check_whisper_model, download_whisper_model, WHISPER_MODELS, _get_hf_model_dir, get_model_by_repo_id, load_model_catalog

        # 兼容 "whisper-large-v3" 或 "large-v3" 的入参格式
        size_key = model_size
        if size_key.startswith("whisper-"):
            size_key = size_key.replace("whisper-", "", 1)
            
        local_files_only = False
        resolved_model_path = model_size

        # 优先检测规整的本地物理路径，如 resources/models/asr/Systran/faster-whisper-tiny
        try:
            from app.services.model_manager import _get_models_root
            local_whisper_dir = _get_models_root() / "asr" / "Systran" / f"faster-whisper-{size_key}"
            local_whisper_dir_str = str(local_whisper_dir.resolve())
        except Exception:
            local_whisper_dir_str = os.path.normpath(f"resources/models/asr/Systran/faster-whisper-{size_key}")
            
        if os.path.isdir(local_whisper_dir_str) and (
            os.path.exists(os.path.join(local_whisper_dir_str, "model.bin")) or
            os.path.exists(os.path.join(local_whisper_dir_str, "model.onnx"))
        ):
            resolved_model_path = local_whisper_dir_str
            local_files_only = True
            logger.info(f"[ASR] 检测到规整的本地内置 Whisper-{size_key} 模型，执行 100% 本地物理绝对路径直读: {resolved_model_path}")
        
        elif size_key in WHISPER_MODELS:
            try:
                if not check_whisper_model(size_key):
                    logger.info(f"ASR model '{size_key}' not found locally. Starting auto-download via central catalog...")
                    download_whisper_model(size_key)
                    if not check_whisper_model(size_key):
                        raise RuntimeError(f"ASR model '{size_key}' could not be verified after auto-download.")
                
                # Prefer catalog for repo
                catalog_entry = get_model_by_repo_id(f"Systran/faster-whisper-{size_key}")
                repo = catalog_entry["repo_id"] if catalog_entry else WHISPER_MODELS[size_key]["hf_repo"]
                model_dir = _get_hf_model_dir(repo)
                snapshots_dir = model_dir / "snapshots"
                snapshots = list(snapshots_dir.iterdir())
                if snapshots:
                    latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)
                    resolved_model_path = str(latest_snapshot.absolute())
                    local_files_only = True
                    logger.info(f"Resolved ASR model '{model_size}' to local offline path: {resolved_model_path}")
                else:
                    logger.warning(f"No snapshot found for ASR model '{size_key}' even though check_whisper_model returned True.")
            except Exception as model_err:
                logger.error(f"Error resolving offline ASR model path: {model_err}. Falling back to default online initialization.")
                resolved_model_path = model_size
                local_files_only = False
        elif os.path.isdir(model_size):
            resolved_model_path = model_size
            local_files_only = True
            logger.info(f"ASR model path is already a directory: {resolved_model_path}")

        # ---------- 设备探测 ----------
        use_cuda = False
        if device is None or device == "auto":
            try:
                import torch
                use_cuda = torch.cuda.is_available()
            except Exception:
                use_cuda = False
        else:
            use_cuda = device == "cuda"

        # Determine CPU thread count to prevent full CPU core starvation
        import multiprocessing
        cores = multiprocessing.cpu_count()
        cpu_threads_count = max(1, min(4, cores // 2))
        logger.info(f"Setting WhisperModel cpu_threads={cpu_threads_count} (total CPU cores: {cores})")

        if use_cuda:
            _model_device = "cuda"
            _model_compute = compute_type or "float16"
            try:
                _thread_local.model_instance = WhisperModel(
                    model_size_or_path=resolved_model_path,
                    device="cuda",
                    compute_type=_model_compute,
                    local_files_only=local_files_only,
                    cpu_threads=cpu_threads_count,
                )
                logger.info(f"ASR model loaded on CUDA: {model_size} (thread={threading.current_thread().name})")
            except Exception as e:
                logger.warning(f"CUDA load failed, fallback to CPU: {e}")
                use_cuda = False

        if not use_cuda:
            _model_device = "cpu"
            _model_compute = compute_type or "int8"
            _thread_local.model_instance = WhisperModel(
                model_size_or_path=resolved_model_path,
                device="cpu",
                compute_type=_model_compute,
                local_files_only=local_files_only,
                cpu_threads=cpu_threads_count,
            )
            logger.info(f"ASR model loaded on CPU: {model_size} (thread={threading.current_thread().name})")

        return _thread_local.model_instance


# ---------------------------------------------------------------------------
# WhisperX backend — forced-alignment word timing (±10-30ms)
# Reference-aligned with OmniVoice-Studio asr_backend.py WhisperXBackend
# ---------------------------------------------------------------------------

_whisperx_lock = threading.Lock()
_whisperx_instance = None


class _WhisperXEngine:
    """WhisperX: faster-whisper + wav2vec2 forced alignment.

    Auto-detects availability. When whisperx is installed, this provides
    word-level timestamps accurate to ±10-30ms vs Whisper's ±100-300ms.
    """

    def __init__(self, model_name: str = "large-v3"):
        self._model_name = model_name
        self._asr = None
        self._align_cache: Dict = {}
        self._device, self._compute_type = self._pick_device()

    @staticmethod
    def _pick_device() -> tuple:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda", "float16"
        except Exception:
            pass
        return "cpu", "int8"

    @staticmethod
    def is_available() -> bool:
        try:
            import whisperx  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _allow_vad_pickle_globals():
        """Register pickle classes that pyannote's VAD checkpoint requires.

        PyTorch 2.6+ secure unpickler refuses omegaconf/typing classes
        from pyannote VAD checkpoints without explicit allowlisting.
        """
        try:
            import torch.serialization as _ts
        except Exception:
            return
        add = getattr(_ts, "add_safe_globals", None)
        if add is None:
            return

        allow = []
        try:
            from omegaconf.listconfig import ListConfig
            from omegaconf.dictconfig import DictConfig
            from omegaconf.base import ContainerMetadata, Metadata
            allow += [ListConfig, DictConfig, ContainerMetadata, Metadata]
        except Exception:
            pass
        try:
            import typing
            allow += [typing.Any]
        except Exception:
            pass
        try:
            from collections import OrderedDict, defaultdict
            allow += [OrderedDict, defaultdict]
        except Exception:
            pass
        if allow:
            try:
                add(allow)
            except Exception:
                pass

    def _ensure_asr(self):
        if self._asr is not None:
            return
        import whisperx
        logger.info(f"WhisperX loading ASR {self._model_name} on {self._device} ({self._compute_type})")
        self._allow_vad_pickle_globals()
        self._asr = whisperx.load_model(
            self._model_name,
            device=self._device,
            compute_type=self._compute_type,
        )

    def _get_align(self, language_code: str):
        if language_code in self._align_cache:
            return self._align_cache[language_code]
        import whisperx
        try:
            model, metadata = whisperx.load_align_model(
                language_code=language_code, device=self._device,
            )
            self._align_cache[language_code] = (model, metadata)
            return model, metadata
        except Exception as e:
            logger.info(f"WhisperX: no alignment model for {language_code!r} ({e}), using native timestamps")
            self._align_cache[language_code] = None
            return None

    def transcribe(self, audio_path: str, *, word_timestamps: bool = True) -> dict:
        """Transcribe with WhisperX + optional forced alignment.

        Returns dict compatible with segmentation.segment_transcript():
          {"segments": [{start, end, text, words: [{word, start, end}]}], "language": str}
        """
        import whisperx
        self._ensure_asr()
        logger.info(f"WhisperX transcribing {audio_path} (word_timestamps={word_timestamps})")
        audio = whisperx.load_audio(audio_path)
        try:
            result = self._asr.transcribe(audio)
        except IndexError:
            # VAD produces 0 segments on silent audio
            logger.info("WhisperX: IndexError (0 VAD segments), returning empty result")
            return {"segments": [], "language": "zh"}

        lang = result.get("language", "zh")

        if word_timestamps:
            align = self._get_align(lang)
            if align is not None:
                model_a, metadata = align
                try:
                    result = whisperx.align(
                        result["segments"], model_a, metadata, audio,
                        self._device, return_char_alignments=False,
                    )
                except Exception as e:
                    logger.warning(f"WhisperX alignment failed: {e}, using raw timestamps")

        segments = result.get("segments", [])
        return {
            "segments": [
                {
                    "text": seg.get("text", ""),
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                    "words": [
                        {"word": w.get("word", ""), "start": w.get("start", 0), "end": w.get("end", 0)}
                        for w in (seg.get("words", []) if word_timestamps else [])
                    ],
                }
                for seg in segments
            ],
            "language": lang,
        }

    def unload(self):
        self._asr = None
        self._align_cache.clear()
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ASR Service
# ---------------------------------------------------------------------------

class ASRService:
    """ASR 语音识别服务（WhisperX > faster-whisper > fallback）"""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        """取消正在进行的识别"""
        self._cancelled = True

    def _recognize_whisperx(
        self,
        audio_path: str,
        *,
        language: str,
        model: str,
        tag: str,
        progress_callback: Optional[Callable],
    ) -> ASRResult:
        """WhisperX recognition path with wav2vec2 forced alignment."""
        global _whisperx_instance
        if progress_callback:
            progress_callback(0, "加载 WhisperX 模型（含 wav2vec2 强制对齐）...")

        with _whisperx_lock:
            if _whisperx_instance is None:
                _whisperx_instance = _WhisperXEngine(model_name=model)
            wx = _whisperx_instance

        if self._cancelled:
            return ASRResult(segments=[], language=language, duration=0.0)

        if progress_callback:
            progress_callback(10, "WhisperX 转写 + 强制对齐中...")

        wx_result = wx.transcribe(audio_path, word_timestamps=True)
        detected_lang = wx_result.get("language", language)
        raw_segments = wx_result.get("segments", [])

        if progress_callback:
            progress_callback(60, f"WhisperX 识别完成，语言: {detected_lang}，正在分段...")

        # Estimate total duration from last segment
        total_duration = 0.0
        for s in raw_segments:
            end = s.get("end")
            if isinstance(end, (int, float)) and end > total_duration:
                total_duration = end
        if total_duration <= 0:
            total_duration = 1.0

        # Professional segmentation
        try:
            from app.services.analyze.segmentation import segment_transcript
            whisper_dict = {
                "segments": raw_segments,
                "text": " ".join(s.get("text", "") for s in raw_segments),
            }
            seg_dicts = segment_transcript(whisper_dict, total_duration)
        except Exception as seg_err:
            logger.warning(f"Segmentation failed: {seg_err}, using raw segments")
            seg_dicts = [
                {"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", ""), "speaker_id": "Speaker 1"}
                for s in raw_segments if s.get("text")
            ]

        segments: List[ASRSegment] = [
            ASRSegment(
                id=str(i + 1),
                text=d["text"],
                start=d["start"],
                end=d["end"],
                speaker=d.get("speaker_id", ""),
            )
            for i, d in enumerate(seg_dicts) if d.get("text")
        ]

        duration = max((s.end for s in segments), default=0.0)
        result = ASRResult(segments=segments, language=detected_lang, duration=duration)
        logger.info(f"ASR [WhisperX] done: {tag} → {len(segments)} segments, {duration:.1f}s")

        if progress_callback:
            progress_callback(100, f"识别完成 (WhisperX): 共 {len(segments)} 段")
        return result

    def recognize(
        self,
        audio_path: str,
        language: str = "zh",
        model: str = "base",
        video_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        engine: str = "auto",
    ) -> ASRResult:
        """
        执行本地语音识别

        Args:
            audio_path: 音频文件路径 (16kHz mono WAV 推荐)
            language: 语言代码 ('zh', 'en', 'ja', 'auto')
            model: 模型大小 ('tiny', 'base', 'small', 'medium', 'large-v3')
            video_id: 视频标识（仅用于日志）
            progress_callback: 进度回调 fn(progress: int, message: str)
            engine: ASR 引擎 ('auto' | 'whisperx' | 'faster_whisper')

        Returns:
            ASRResult 包含识别片段列表
        """
        self._cancelled = False

        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        tag = video_id or Path(audio_path).stem
        logger.info(f"ASR start: {tag} (model={model}, lang={language}, engine={engine})")

        # ── WhisperX fast-path (reference-aligned) ──────────────────────
        # When whisperx is installed and engine is "auto" or "whisperx",
        # use WhisperX for ±10-30ms word-level timestamps via wav2vec2 forced alignment.
        use_whisperx = engine in ("auto", "whisperx") and _WhisperXEngine.is_available()
        if use_whisperx:
            try:
                return self._recognize_whisperx(
                    audio_path, language=language, model=model,
                    tag=tag, progress_callback=progress_callback,
                )
            except Exception as wx_err:
                logger.warning(f"WhisperX failed: {wx_err}, falling back to faster-whisper")
                if engine == "whisperx":
                    raise  # explicit request should not silently degrade

        # ── faster-whisper path (existing) ────────────────────────────────
        if progress_callback:
            progress_callback(0, "加载语音识别模型（首次加载可能需要较长时间）...")

        whisper = _get_model(model_size=model)
        
        if progress_callback:
            progress_callback(10, "模型加载完成，准备开始识别...")

        if self._cancelled:
            logger.warning(f"ASR cancelled before transcription: {tag}")
            return ASRResult(segments=[], language=language, duration=0.0)

        if progress_callback:
            progress_callback(10, "开始语音识别...")

        # ---------- 转写 ----------
        lang_param = None if language == "auto" else language
        seg_iter, info = whisper.transcribe(
            audio_path,
            language=lang_param,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt="以下是普通话的句子",
        )

        detected_lang = info.language or language
        logger.info(f"ASR detected language: {detected_lang} "
                     f"(prob={info.language_probability:.2f})")

        if progress_callback:
            progress_callback(30, f"识别语言: {detected_lang}")

        # ---------- 遍历 segments ----------
        if progress_callback:
            progress_callback(10, "正在处理识别结果...")

        # 收集原始 whisper segments（含 word timestamps）用于专业分段
        raw_segments: List[Dict] = []
        seg_count = 0

        # 获取音频总长度，用于精确的进度计算
        total_duration = getattr(info, "duration", 0.0)
        if not isinstance(total_duration, (int, float)) or total_duration <= 0:
            total_duration = 1.0

        for segment in seg_iter:
            if self._cancelled:
                logger.warning(f"ASR cancelled mid-transcription: {tag}")
                break

            seg_dict: Dict = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": [],
            }
            if segment.words:
                for word in segment.words:
                    seg_dict["words"].append({
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                    })
            raw_segments.append(seg_dict)

            seg_count += 1
            if progress_callback:
                ratio = min(1.0, max(0.0, segment.end / total_duration))
                pct = min(95, 10 + int(ratio * 85))
                progress_callback(pct, f"识别中: 已处理 {segment.end:.1f}秒 / 共 {total_duration:.1f}秒 (共 {seg_count}段)")

        # ── Professional segmentation (reference-aligned) ──────────────
        # Replaces the old punctuation-based splitting with broadcast-grade
        # segmentation: MIN_DUR=1.5s, IDEAL_DUR=4.5s, multi-pass merge/stitch.
        try:
            from app.services.analyze.segmentation import segment_transcript
            whisper_result = {
                "segments": raw_segments,
                "text": " ".join(s["text"] for s in raw_segments),
            }
            seg_dicts = segment_transcript(whisper_result, total_duration)
        except Exception as seg_err:
            logger.warning(f"Professional segmentation failed: {seg_err}, falling back to raw")
            seg_dicts = [
                {"start": s["start"], "end": s["end"], "text": s["text"], "speaker_id": "Speaker 1"}
                for s in raw_segments if s["text"]
            ]

        segments: List[ASRSegment] = [
            ASRSegment(
                id=str(i + 1),
                text=d["text"],
                start=d["start"],
                end=d["end"],
                speaker=d.get("speaker_id", ""),
            )
            for i, d in enumerate(seg_dicts) if d.get("text")
        ]

        duration = max((s.end for s in segments), default=0.0)
        result = ASRResult(segments=segments, language=detected_lang, duration=duration)

        logger.info(f"ASR done: {tag} → {len(segments)} segments, {duration:.1f}s")

        if progress_callback:
            progress_callback(100, f"识别完成: 共 {len(segments)} 段")

        return result

    def save_result(self, result: ASRResult, output_path: str):
        """将识别结果保存为 JSON 文件"""
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"ASR result saved: {output_path}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _has_punctuation(word: str) -> bool:
    """判断单词/字是否包含标点符号"""
    punct = set(".,!?;:，。！？；：、")
    return any(c in punct for c in word)


# ---------------------------------------------------------------------------
# 独立入口 – 直接对音频文件执行 ASR
# ---------------------------------------------------------------------------

def whisper_asr(
    audio_path: str,
    model: str = "base",
    language: str = "zh",
    progress_callback=None,
) -> List[Dict]:
    """
    快捷函数：对单个音频文件执行语音识别

    Returns:
        [{"text": ..., "start": ..., "end": ..., "speaker": ...}]
    """
    service = ASRService()
    result = service.recognize(
        audio_path=audio_path,
        language=language,
        model=model,
        progress_callback=progress_callback,
    )
    return [s.to_dict() for s in result.segments]


# ---------------------------------------------------------------------------
# ASR Backend Protocol (reference-aligned: OmniVoice-Studio ASRBackend ABC)
# ---------------------------------------------------------------------------

class ASRBackend(ABC):
    """Abstract base class for ASR backends.

    All ASR engines (WhisperX, faster-whisper, SenseVoice) conform to this
    protocol so the pipeline can swap them transparently.
    """
    id: str = "base"
    display_name: str = "Base ASR"

    @classmethod
    @abstractmethod
    def is_available(cls) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def transcribe(self, audio_path: str, *, word_timestamps: bool = True) -> dict:
        """Return raw whisper-compatible output dict."""

    def unload(self) -> None:
        """Release the model from memory."""
        pass


def list_asr_backends() -> List[Dict]:
    """Return metadata about available ASR backends (reference-aligned).

    Similar to TTS ``list_backends()`` — each entry has id, display_name,
    available, status, and priority.
    """
    backends = []

    # 1. WhisperX
    wx_avail, wx_msg = True, "ready"
    try:
        import whisperx  # noqa: F401
    except ImportError as e:
        wx_avail, wx_msg = False, f"whisperx not installed: {e}"
    backends.append({
        "id": "whisperx",
        "display_name": "WhisperX (wav2vec2 forced alignment, ±10-30ms)",
        "available": wx_avail,
        "status": wx_msg,
        "priority": 0,
        "description": "faster-whisper + wav2vec2 强制对齐，词级时间戳精度最高",
    })

    # 2. Faster-Whisper
    fw_avail, fw_msg = True, "ready"
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError as e:
        fw_avail, fw_msg = False, f"faster-whisper not installed: {e}"
    backends.append({
        "id": "faster_whisper",
        "display_name": "Faster-Whisper (CTranslate2, cross-platform)",
        "available": fw_avail,
        "status": fw_msg,
        "priority": 1,
        "description": "CTranslate2 优化 Whisper，跨平台稳定首选",
    })

    # 3. SenseVoice
    sv_avail, sv_msg = True, "ready"
    try:
        from funasr import AutoModel  # noqa: F401
    except ImportError as e:
        sv_avail, sv_msg = False, f"funasr not installed: {e}"
    backends.append({
        "id": "sensevoice",
        "display_name": "SenseVoice (达摩院，中文优化 + 情感/事件检测)",
        "available": sv_avail,
        "status": sv_msg,
        "priority": 2,
        "description": "阿里达摩院 SenseVoice，中文场景首选，支持情感/事件检测",
    })

    return backends


def get_active_asr_backend(engine: str = "auto") -> str:
    """Resolve the active ASR backend by config or auto-detection.

    Args:
        engine: ``"auto"`` selects the best available (WhisperX > faster-whisper
            > SenseVoice). Or specify ``"whisperx"`` / ``"faster_whisper"`` /
            ``"sensevoice"`` explicitly.

    Returns:
        The resolved engine id string.
    """
    if engine != "auto":
        return engine

    # Auto-detect: prefer WhisperX > faster-whisper > sensevoice
    for b in list_asr_backends():
        if b["available"]:
            logger.info(f"ASR auto-detect: selected {b['id']} ({b['display_name']})")
            return b["id"]

    logger.warning("No ASR backend available! Install faster-whisper or whisperx.")
    return "faster_whisper"  # will fail gracefully at runtime
