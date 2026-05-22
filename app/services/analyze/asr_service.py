"""
ASR 语音识别服务 - 支持多种引擎

引擎选项:
    - faster-whisper: 基于 OpenAI Whisper 的优化版本
    - sensevoice: 阿里达摩院 SenseVoice，针对中文优化

通过 config.toml 配置:
    [asr]
    engine = "faster_whisper"  # faster_whisper | sensevoice
    model = "large-v3"         # faster-whisper: tiny/base/small/medium/large-v3/distil-large-v3
                              # sensevoice: SenseVoice-small/SenseVoice-large
"""

import os
import threading
from typing import Any, List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger


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


def _get_model(model_size: str = "large-v3", device: Optional[str] = None,
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
        from app.services.model_manager import check_whisper_model, download_whisper_model, WHISPER_MODELS, _get_hf_model_dir
        
        # 兼容 "whisper-large-v3" 或 "large-v3" 的入参格式
        size_key = model_size
        if size_key.startswith("whisper-"):
            size_key = size_key.replace("whisper-", "", 1)
            
        local_files_only = False
        resolved_model_path = model_size
        
        if size_key in WHISPER_MODELS:
            try:
                if not check_whisper_model(size_key):
                    logger.info(f"ASR model '{size_key}' not found locally. Starting auto-download from ModelScope...")
                    download_whisper_model(size_key)
                    if not check_whisper_model(size_key):
                        raise RuntimeError(f"ASR model '{size_key}' could not be verified after auto-download.")
                
                info = WHISPER_MODELS[size_key]
                model_dir = _get_hf_model_dir(info["hf_repo"])
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
# ASR Service
# ---------------------------------------------------------------------------

class ASRService:
    """ASR 语音识别服务（本地 faster-whisper）"""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        """取消正在进行的识别"""
        self._cancelled = True

    def recognize(
        self,
        audio_path: str,
        language: str = "zh",
        model: str = "large-v3",
        video_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> ASRResult:
        """
        执行本地语音识别

        Args:
            audio_path: 音频文件路径 (16kHz mono WAV 推荐)
            language: 语言代码 ('zh', 'en', 'ja', 'auto')
            model: 模型大小 ('tiny', 'base', 'small', 'medium', 'large-v3')
            video_id: 视频标识（仅用于日志）
            progress_callback: 进度回调 fn(progress: int, message: str)

        Returns:
            ASRResult 包含识别片段列表
        """
        self._cancelled = False

        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        tag = video_id or Path(audio_path).stem
        logger.info(f"ASR start: {tag} (model={model}, lang={language})")

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
        # 先发送一个中间进度，让用户知道开始处理了
        if progress_callback:
            progress_callback(35, "正在处理识别结果...")
        segments: List[ASRSegment] = []
        total_segments_approx = 50  # 用于进度估算
        seg_count = 0
        seg_start = 0.0
        seg_end = 0.0
        seg_text = ""

        for segment in seg_iter:
            if self._cancelled:
                logger.warning(f"ASR cancelled mid-transcription: {tag}")
                break

            # 按标点断句
            if segment.words:
                for word in segment.words:
                    if not seg_text:
                        seg_start = word.start
                    seg_text += word.word
                    seg_end = word.end

                    # 如果包含标点则输出一个片段
                    if _has_punctuation(word.word):
                        text = seg_text.rstrip(".,!?;:，。！？；：、")
                        if text:
                            segments.append(ASRSegment(
                                id=str(len(segments) + 1),
                                text=text,
                                start=seg_start,
                                end=seg_end,
                            ))
                        seg_text = ""
            else:
                # 没有词级时间戳时按 segment 级别输出
                text = segment.text.strip()
                if text:
                    segments.append(ASRSegment(
                        id=str(len(segments) + 1),
                        text=text,
                        start=segment.start,
                        end=segment.end,
                    ))

            seg_count += 1
            if progress_callback and seg_count % 5 == 0:
                pct = min(85, 30 + int(seg_count / total_segments_approx * 55))
                progress_callback(pct, f"识别中… 已处理 {seg_count} 段")

        # 处理最后一段无标点的文本
        if seg_text.strip():
            segments.append(ASRSegment(
                id=str(len(segments) + 1),
                text=seg_text.strip(),
                start=seg_start,
                end=seg_end,
            ))

        duration = max((s.end for s in segments), default=0.0)
        result = ASRResult(segments=segments, language=detected_lang, duration=duration)

        logger.info(f"ASR done: {tag} → {len(segments)} segments, {duration:.1f}s")

        if progress_callback:
            progress_callback(100, f"识别完成: {len(segments)} 段")

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
